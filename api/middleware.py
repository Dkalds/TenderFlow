"""Middlewares ASGI personalizados para la API REST.

* :class:`SecurityHeadersMiddleware` — Añade cabeceras de seguridad OWASP (ASGI puro).
* :class:`RateLimitMiddleware`       — Rate limiting por IP; el almacén lo elige
  ``services.rate_limiting.get_rate_limiter`` (Redis o tabla ``rate_limits``).
* :class:`CostTrackingMiddleware`    — Estima coste por request (Prometheus).
* :class:`AccessLogMiddleware`       — Access log estructurado con métricas RED.

Todos diseñados para ser idempotentes y "fail-open" ante errores de infra.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from observability.logging import get_logger
from services.rate_limiting import get_rate_limiter

log = get_logger(__name__)


# ───────────────────────────── Security headers ─────────────────────────────


class SecurityHeadersMiddleware:
    """Añade cabeceras de seguridad recomendadas por OWASP.

    Implementado como middleware ASGI puro para evitar el overhead de
    ``BaseHTTPMiddleware`` (que bufferiza el body completo). Este middleware
    solo necesita interceptar los headers de la respuesta, no el body.

    Cabeceras añadidas:
    - ``X-Content-Type-Options: nosniff``
    - ``X-Frame-Options: DENY``
    - ``Referrer-Policy: strict-origin-when-cross-origin``
    - ``Permissions-Policy``: deshabilita APIs sensibles del navegador
    - ``Strict-Transport-Security``: solo si la request llega por HTTPS
    - ``Content-Security-Policy``: configurable, default seguro para JSON API
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        csp: str = "default-src 'none'; frame-ancestors 'none'; report-uri /api/v1/security/csp-report",
        hsts_max_age: int = 31_536_000,  # 1 año
    ) -> None:
        self.app = app
        self._csp = csp
        self._hsts = f"max-age={hsts_max_age}; includeSubDomains"
        # Pre-compute header pairs as bytes for performance
        self._base_headers: list[tuple[bytes, bytes]] = [
            (b"x-content-type-options", b"nosniff"),
            (b"x-frame-options", b"DENY"),
            (b"referrer-policy", b"strict-origin-when-cross-origin"),
            (
                b"permissions-policy",
                b"geolocation=(), microphone=(), camera=(), payment=(), usb=()",
            ),
            (b"content-security-policy", csp.encode()),
        ]
        self._hsts_header: tuple[bytes, bytes] = (
            b"strict-transport-security",
            self._hsts.encode(),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Detectar si es HTTPS (directo o detrás de proxy)
        is_https = scope.get("scheme") == "https"
        if not is_https:
            # Check X-Forwarded-Proto en los headers de la request
            for header_name, header_value in scope.get("headers", []):
                if header_name == b"x-forwarded-proto" and header_value == b"https":
                    is_https = True
                    break

        async def _send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing_names = {h[0].lower() for h in headers}
                for name, value in self._base_headers:
                    if name not in existing_names:
                        headers.append((name, value))
                if is_https and b"strict-transport-security" not in existing_names:
                    headers.append(self._hsts_header)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, _send_with_security_headers)


# ───────────────────────────── Rate limiting ────────────────────────────────


def _trusted_client_ip(request: Request) -> str:
    """Extrae la IP real del cliente validando proxies de confianza.

    Solo honra ``X-Forwarded-For`` si la conexión TCP directa viene de una IP
    en ``FORWARDED_ALLOW_IPS`` (configurado en settings). Esto evita que un
    cliente externo inyecte una IP falsa en la cabecera y eluda el rate-limit
    basado en IP.

    Returns:
        IP del cliente (string). Nunca lanza — devuelve "unknown" ante errores.
    """
    try:
        import ipaddress

        from config import settings

        allowed_proxies: set[str] = {
            ip.strip()
            for ip in getattr(settings, "FORWARDED_ALLOW_IPS", "127.0.0.1").split(",")
            if ip.strip()
        }
        direct_ip = request.client.host if request.client else None

        def _is_trusted_proxy(ip: str) -> bool:
            if "*" in allowed_proxies:
                return False
            try:
                candidate = ipaddress.ip_address(ip)
                return any(
                    candidate in ipaddress.ip_network(value, strict=False)
                    for value in allowed_proxies
                )
            except ValueError:
                return ip in allowed_proxies

        if "*" in allowed_proxies:
            # Semántica "un salto de confianza" para PaaS (Render): el único
            # peer TCP posible es el proxy de la plataforma, que APPENDEA la IP
            # real del cliente al final de X-Forwarded-For. El último hop es
            # por tanto fiable; los de la izquierda los escribe el cliente.
            # Hasta 2026-08 este caso devolvía request.client.host — que
            # uvicorn, honrando el mismo FORWARDED_ALLOW_IPS="*", ya había
            # reescrito con el hop MÁS A LA IZQUIERDA (spoofeable): el
            # rate-limit por IP y el allowlist de /metrics se alimentaban de
            # una IP elegida por el cliente (RFC-051).
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                last_hop = forwarded.split(",")[-1].strip()
                if last_hop:
                    return last_hop
            return direct_ip or "unknown"

        if direct_ip and _is_trusted_proxy(direct_ip):
            # Petición viene de un proxy de confianza — honrar XFF
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                # Recorremos la cadena desde el proxy más cercano. Solo las
                # IPs de proxies configurados son fiables; la primera no
                # confiable es el cliente visto por nuestra infraestructura.
                for hop in reversed([part.strip() for part in forwarded.split(",")]):
                    if hop and not _is_trusted_proxy(hop):
                        return hop
        return direct_ip or "unknown"
    except Exception:
        return "unknown"


def _client_key(request: Request) -> str:
    """Identifica al cliente **solo** por IP verificada, nunca por API-Key.

    Un bucket por API-Key permitiría eludir el límite rotando claves (crearlas
    es barato), así que la cuota se ancla a la IP: el recurso caro de falsificar.
    La IP se obtiene a través de ``_trusted_client_ip``, que solo honra
    ``X-Forwarded-For`` si la petición viene de un proxy de confianza.
    """
    ip = _trusted_client_ip(request)
    return f"ip:{ip}"


# Endpoints que consumen más CPU/IO reciben un rate limit más bajo.
# Paths no listados usan el default del middleware.
#
# Esta tabla solo cubre rutas *sin* path params: se compara por igualdad exacta,
# así que "/api/v1/exports" no arrastra a "/api/v1/exports/{job_id}".
_HEAVY_ENDPOINT_LIMITS: dict[str, int] = {
    "/api/v1/exports": 20,
    # Descarga síncrona: hasta 50.000 filas y, con format=pdf, render en el
    # propio worker. Es el camino recomendado de export, no el job asíncrono.
    "/api/v1/exports/download": 10,
    "/api/v1/feedback/queue": 30,
    "/api/v1/search/semantic": 30,
    "/api/v1/ask": 10,
    "/api/v1/ask/models": 30,
}

# Rutas pesadas **con** path params. ``BaseHTTPMiddleware`` corre antes del
# routing, así que aquí solo se ve el path crudo y nunca el template: indexar
# por literal exacto hacía que estas dos entradas no matchearan jamás y
# corrieran al límite por defecto. Los patrones van anclados a ambos extremos
# para no capturar rutas vecinas.
_HEAVY_ENDPOINT_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    # /licitaciones/{id_externo:path}/explain — el id puede contener '/'
    # (p.ej. "PA-S 2026/000058"), por eso el comodín admite barras.
    (re.compile(r"^/api/v1/licitaciones/.+/explain$"), 30),
    # /models/{name}/activate/{version}
    (re.compile(r"^/api/v1/models/[^/]+/activate/[^/]+$"), 10),
)


def _effective_max_calls(path: str, default: int) -> int:
    """Límite de requests por ventana aplicable a ``path``.

    Si varias reglas matchean gana la **más restrictiva** (el mínimo):
    pasarse de estricto cuesta un 429 recuperable, quedarse corto deja el
    endpoint caro sin la protección que se le quiso poner.
    """
    limits = [limit for pattern, limit in _HEAVY_ENDPOINT_PATTERNS if pattern.match(path)]
    exact = _HEAVY_ENDPOINT_LIMITS.get(path)
    if exact is not None:
        limits.append(exact)
    return min(limits) if limits else default


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting global por IP sobre la API REST.

    Usa :func:`services.rate_limiting.get_rate_limiter` como backend (Redis o
    la tabla ``rate_limits``, según configuración).
    Devuelve ``429 Too Many Requests`` con cabeceras estándar cuando se excede.

    Excluye paths configurables (e.g. ``/api/v1/health``) para no bloquear LBs.

    Los endpoints pesados (inferencia ML, exports) tienen un límite inferior;
    ver :func:`_effective_max_calls`.

    Args:
        app: Aplicación ASGI a envolver.
        max_calls: Máximo de requests permitidas en la ventana (endpoints estándar).
        window_seconds: Tamaño de la ventana en segundos.
        exclude_paths: Iterable de paths exactos a excluir (e.g. health, docs).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_calls: int = 120,
        window_seconds: float = 60.0,
        exclude_paths: tuple[str, ...] = (
            "/",
            "/api/v1/health",
            "/api/docs",
            "/api/redoc",
            "/api/openapi.json",
        ),
    ) -> None:
        super().__init__(app)
        self._max = max_calls
        self._window = window_seconds
        self._exclude = frozenset(exclude_paths)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        if path in self._exclude or path.startswith(("/api/docs", "/api/redoc")):
            return await call_next(request)

        client = _client_key(request)
        # BaseHTTPMiddleware se ejecuta antes del routing: un bucket global
        # por cliente evita el bypass por path params variables.
        rate_key = f"api:{client}"
        # Endpoints pesados (ML inference, exports) tienen límite inferior.
        effective_max = _effective_max_calls(path, self._max)
        allowed = get_rate_limiter().check(
            rate_key,
            max_calls=effective_max,
            window_seconds=self._window,
        )
        if not allowed:
            log.warning("rate_limit_exceeded", client=client, path=path)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit excedido. Intenta de nuevo más tarde.",
                    "limit": effective_max,
                    "window_seconds": self._window,
                },
                headers={
                    "Retry-After": str(int(self._window)),
                    "X-RateLimit-Limit": str(effective_max),
                    "X-RateLimit-Window": str(int(self._window)),
                },
            )
        return await call_next(request)


# ───────────────────── Cost tracking (E7) ───────────────────────────────


class CostTrackingMiddleware(BaseHTTPMiddleware):
    """Estima coste por request y lo acumula como counter Prometheus.

    Modelo simple: cada request tiene un coste base de 0.0001 USD + un
    factor proporcional a la duración (CPU/IO). Esto permite a Finance ver
    de un vistazo qué endpoints son los más caros.

    El coste se publica como ``api_cost_estimate_total{operation}`` en
    micros (USD * 1e6) para evitar problemas de precisión float en el TSDB.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        base_usd: float = 0.0001,
        per_second_usd: float = 0.001,
    ) -> None:
        super().__init__(app)
        self._base = base_usd
        self._per_s = per_second_usd

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        import time

        t0 = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            dt = time.monotonic() - t0
            usd = self._base + (dt * self._per_s)
            try:
                from observability.runtime_metrics import api_cost_estimate_total

                # Usar route template para evitar cardinalidad explosiva
                route = request.scope.get("route")
                op = getattr(route, "path", None) or "unmatched"
                api_cost_estimate_total.labels(operation=op).inc(int(usd * 1e6))
            except Exception:
                pass
        return response


# ───────────────────── Access log + métricas RED ──────────────────────────


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Access log estructurado por request.

    Registra por request:
    - método, path, status, duración en ms
    - key_hash_prefix (8 chars — para correlación sin exponer el token)
    - correlation_id (si está en contextvars)
    - client IP

    Las métricas RED (Rate, Errors, Duration) las gestiona
    ``prometheus-fastapi-instrumentator`` (inicializado en ``api.app``).
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        import time

        t0 = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            raise
        finally:
            dt_ms = (time.monotonic() - t0) * 1000
            # Usar el path template de la ruta (e.g. "/licitaciones/{id}") en lugar
            # del path crudo ("/licitaciones/123") para evitar cardinalidad explosiva
            # en métricas Prometheus cuando los IDs forman parte de la URL.
            route = request.scope.get("route")
            path = getattr(route, "path", None) or request.url.path.split("?")[0]
            method = request.method
            # Usar hash prefix en lugar de los primeros caracteres del API key
            # para evitar reducir el espacio de brute-force en los logs.
            raw_key = request.headers.get("X-API-Key") or ""
            key_prefix = hashlib.sha256(raw_key.encode()).hexdigest()[:12] if raw_key else "-"
            client_ip = _trusted_client_ip(request)

            log.info(
                "http_request",
                method=method,
                path=path,
                status=status_code,
                duration_ms=round(dt_ms, 1),
                key_prefix=key_prefix,
                client_ip=client_ip,
            )

        return response


# ───────────────────────────── ETag caching ──────────────────────────────────


class ETagMiddleware(BaseHTTPMiddleware):
    """Añade ``ETag`` a respuestas GET 200 y responde 304 si ``If-None-Match`` coincide.

    Sólo actúa sobre respuestas con ``Content-Type: application/json`` y
    tamaño < ``max_bytes`` para no bloquear streams ni ficheros grandes.

    El ETag es un hash SHA-1 del cuerpo, prefijado con ``W/`` (weak).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_bytes: int = 512 * 1024,  # 512 KB
    ) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        import hashlib

        if request.method != "GET":
            return await call_next(request)

        response = await call_next(request)

        # Una respuesta solicitada con cookie o API key puede contener estado
        # personalizado; ningún cache compartido debe conservarla.
        if request.headers.get("cookie") or request.headers.get("x-api-key"):
            response.headers["Cache-Control"] = "private, no-store"
            return response

        if response.status_code != 200:
            return response

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        # Leer el cuerpo completo (sólo si es razonable en tamaño)
        body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            body += chunk
            if len(body) > self._max_bytes:
                # Demasiado grande: devolver sin ETag (reconstruir la respuesta)
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

        etag = 'W/"' + hashlib.sha256(body).hexdigest()[:24] + '"'
        if_none_match = request.headers.get("if-none-match", "")
        # RFC 7232: If-None-Match can contain multiple ETags separated by commas
        if if_none_match and etag in {t.strip() for t in if_none_match.split(",")}:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})

        headers = dict(response.headers)
        headers["ETag"] = etag
        headers["Cache-Control"] = headers.get("Cache-Control", "no-cache")
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
