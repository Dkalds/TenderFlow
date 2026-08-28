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

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response
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
    # /licitaciones/{id}/ficha-pliego/extract — la única ruta mutante de
    # /licitaciones y la más cara de la API: descarga contra PLACSP los pliegos
    # pendientes, extrae el PDF en un proceso aislado y pide al LLM una ficha de
    # hasta 3.500 tokens. Mismo tope que /ask porque el coste es de la misma
    # naturaleza —una llamada a proveedor por petición—, y corría al default de
    # 120/min por no estar en esta tabla. El comodín admite barras: el id
    # externo puede llevarlas (ver la nota de /explain).
    (re.compile(r"^/api/v1/licitaciones/.+/ficha-pliego/extract$"), 10),
    # /licitaciones/{id}/resumen — abre un SSE, arma contexto RAG con lecturas
    # de BD y streamea tokens del LLM. Es /ask con otro nombre y otra pregunta,
    # así que comparte su tope en vez del default: dejarlo en 120/min convertía
    # el límite de /ask en decorativo (misma capacidad, ruta distinta).
    (re.compile(r"^/api/v1/licitaciones/.+/resumen$"), 10),
    # /models/{name}/activate/{version}
    (re.compile(r"^/api/v1/models/[^/]+/activate/[^/]+$"), 10),
)


# La superficie pública indexable vive bajo este prefijo y necesita su propio
# bucket. Con la clave global `api:{ip}` compartida, dos cosas iban mal a la vez:
# los rastreadores consumían la cuota del usuario autenticado que estuviera
# detrás del mismo NAT, y —lo grave— si Next renderiza en servidor desde una IP
# de egreso única, TODAS las páginas públicas se contaban contra un solo bucket
# de 120/min y la superficie SEO se estrangulaba sola con 429.
#
# El límite es más alto porque el tráfico es cualitativamente distinto:
# lecturas anónimas, cacheables y sin estado, servidas a rastreadores que
# hacen ráfagas por diseño. Sigue siendo una cuota por IP, así que un abusivo
# concreto se corta igual, pero ya no arrastra al resto de la API.
PUBLIC_PATH_PREFIX = "/api/v1/publico/"
PUBLIC_MAX_CALLS = 600

# El único endpoint público de **escritura** (la cola de solicitudes de acceso
# que alimenta el formulario de la landing) necesita bucket propio, no una
# entrada en `_HEAVY_ENDPOINT_LIMITS`.
#
# El motivo es que esa tabla ajusta el tope pero **no** la clave: el contador
# seguiría siendo `publico:{ip}`, compartido con todas las lecturas anónimas.
# Un tope de 5 sobre ese contador significaría que cinco peticiones de un
# rastreador dejan el formulario inservible, y que cada envío consume cuota de
# la superficie SEO. Con clave propia, las dos cosas se limitan por separado.
#
# Cinco por minuto y por IP: un humano rellena el formulario una vez, y lo que
# hay detrás es una cola que revisa una persona.
#
# Al agotarse la cuota este path **no** responde `problem+json` como el resto de
# la API: quien lo consume es un navegador siguiendo un `<form method="post">`,
# así que se le redirige a la página de gracias con el estado de límite. Ver el
# caso propio en `RateLimitMiddleware.dispatch`.
SOLICITUDES_PATH = "/api/v1/publico/solicitudes-acceso"
SOLICITUDES_MAX_CALLS = 5


def _rate_bucket(path: str, client: str) -> tuple[str, int | None]:
    """Clave de cuota y tope propio para ``path``.

    Devuelve ``(clave, tope)``. Un tope ``None`` significa "usa el default del
    middleware", que es como se comporta todo lo que no es superficie pública.
    """
    if path == SOLICITUDES_PATH:
        return f"solicitudes:{client}", SOLICITUDES_MAX_CALLS
    if path.startswith(PUBLIC_PATH_PREFIX):
        return f"publico:{client}", PUBLIC_MAX_CALLS
    return f"api:{client}", None


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
        # BaseHTTPMiddleware se ejecuta antes del routing: un bucket por
        # cliente evita el bypass por path params variables. La superficie
        # pública lleva el suyo aparte (ver `_rate_bucket`).
        rate_key, tope_propio = _rate_bucket(path, client)
        # Endpoints pesados (ML inference, exports) tienen límite inferior.
        effective_max = _effective_max_calls(path, tope_propio or self._max)
        allowed = get_rate_limiter().check(
            rate_key,
            max_calls=effective_max,
            window_seconds=self._window,
        )
        if not allowed:
            log.warning("rate_limit_exceeded", client=client, path=path)

            # El formulario de la landing lo rellena una persona en un
            # navegador, no un cliente de API: aquí un `problem+json` es JSON
            # crudo en pantalla, y `api/routes/publico_solicitudes.py` está
            # escrito entero para que eso no pase en ningún camino de error.
            # El corte por cuota ocurre antes del router, así que la excepción
            # tiene que vivir aquí. Import perezoso por el mismo motivo que el
            # de `problem_429`: no arrastrar el árbol de rutas al importar el
            # middleware.
            if path == SOLICITUDES_PATH:
                from api.routes.publico_solicitudes import ESTADO_LIMITE, destino_error

                return RedirectResponse(
                    destino_error(ESTADO_LIMITE),
                    status_code=status.HTTP_303_SEE_OTHER,
                    headers={"Retry-After": str(int(self._window))},
                )

            # `application/problem+json` como el resto de la API (RFC 7807). El
            # 429 cortocircuita antes del router, así que se construye aquí en
            # vez de en un exception handler; `problem_429` ya existía sin uso.
            from api.errors import problem_429

            return problem_429(effective_max, int(self._window)).response(
                **{
                    "Retry-After": str(int(self._window)),
                    "X-RateLimit-Limit": str(effective_max),
                    "X-RateLimit-Window": str(int(self._window)),
                }
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

# RFC 7232 §4.1: un 304 debe repetir las cabeceras que habrían acompañado al
# 200 y que el cliente necesita para interpretar la respuesta cacheada.
_NOT_MODIFIED_PRESERVED_HEADERS = frozenset(
    {"vary", "x-request-id", "x-correlation-id", "content-language"}
)


class ETagMiddleware(BaseHTTPMiddleware):
    """Añade ``ETag`` a respuestas GET 200 y responde 304 si ``If-None-Match`` coincide.

    Sólo actúa sobre respuestas con ``Content-Type: application/json`` y
    tamaño < ``max_bytes`` para no bloquear streams ni ficheros grandes.

    El ETag es un hash SHA-256 del cuerpo (truncado), prefijado con ``W/`` (weak).

    **Tráfico autenticado.** Hasta 2026-08 una petición con cookie o API key
    salía por un atajo que ponía ``private, no-store`` y devolvía la respuesta
    *sin* ETag. Como prácticamente todos los endpoints exigen autenticación, el
    middleware no emitía un solo ETag en producción: se pagaba el coste de
    bufferizar el cuerpo de cada GET JSON a cambio de nada. Ahora esas
    respuestas llevan ``private, no-cache``, que sigue impidiendo que un caché
    compartido las guarde y además permite la revalidación con 304 — que es
    justo donde está el ahorro de ancho de banda para un SPA que repregunta.
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
        is_authenticated = bool(request.headers.get("cookie") or request.headers.get("x-api-key"))

        # `Vary` no es opcional desde el momento en que la línea de arriba
        # decide el `Cache-Control` leyendo cabeceras de la **petición**: sin
        # declararlo, un CDN o un proxy intermedio no sabe que la respuesta
        # depende de ellas y puede servirle a un visitante anónimo la copia
        # cacheada de uno autenticado. Se emite siempre, también en el 304,
        # porque la dependencia existe igualmente en ese camino.
        vary = "Cookie, X-API-Key"

        # Lo que este middleware NO va a etiquetar con ETag (no-200, streams,
        # descargas) conserva el `private, no-store` de siempre: sin
        # revalidación posible, lo correcto es no guardarlo en ningún sitio.
        es_json = "application/json" in response.headers.get("content-type", "")
        if response.status_code != 200 or not es_json:
            if is_authenticated:
                response.headers["Cache-Control"] = "private, no-store"
            response.headers["Vary"] = vary
            return response

        # Para el JSON que sí lleva ETag, `private` mantiene fuera a los cachés
        # compartidos y `no-cache` obliga a revalidar en cada uso — el 304 sigue
        # siendo válido, y es justo el punto de haber calculado el ETag.
        cache_control = "private, no-cache" if is_authenticated else None

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
            # El 304 conserva las cabeceras de correlación/seguridad de la
            # respuesta original: son las mismas que el cliente habría recibido
            # con un 200, y perderlas rompía el rastro de la petición.
            not_modified = {
                k: v
                for k, v in response.headers.items()
                if k.lower() in _NOT_MODIFIED_PRESERVED_HEADERS
            }
            not_modified["ETag"] = etag
            not_modified["Cache-Control"] = cache_control or "no-cache"
            not_modified["Vary"] = vary
            return Response(status_code=304, headers=not_modified)

        headers = dict(response.headers)
        headers["ETag"] = etag
        headers["Cache-Control"] = cache_control or headers.get("Cache-Control", "no-cache")
        headers["Vary"] = vary
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
