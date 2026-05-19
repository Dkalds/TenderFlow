"""Middlewares ASGI personalizados para la API REST.

* :class:`SecurityHeadersMiddleware` — Añade cabeceras de seguridad OWASP.
* :class:`RateLimitMiddleware`       — Rate limiting per-API-Key sobre SQLite.
* :class:`CostTrackingMiddleware`    — Estima coste por request (Prometheus).
* :class:`AccessLogMiddleware`       — Access log estructurado con métricas RED.

Todos diseñados para ser idempotentes y "fail-open" ante errores de infra.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp

from observability.logging import get_logger
from services.rate_limit_redis import check_rate_limit as _check_rate_limit

log = get_logger(__name__)


# ───────────────────────────── Security headers ─────────────────────────────


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Añade cabeceras de seguridad recomendadas por OWASP.

    Aplicado a todas las respuestas. Cabeceras añadidas:
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
        super().__init__(app)
        self._csp = csp
        self._hsts = f"max-age={hsts_max_age}; includeSubDomains"

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=()",
        )
        headers.setdefault("Content-Security-Policy", self._csp)
        # HSTS solo tiene sentido si el cliente vino por HTTPS (o detrás de proxy TLS)
        if request.url.scheme == "https" or request.headers.get("X-Forwarded-Proto") == "https":
            headers.setdefault("Strict-Transport-Security", self._hsts)
        return response


# ───────────────────────────── Rate limiting ────────────────────────────────


def _client_key(request: Request) -> str:
    """Identifica al cliente por API-Key (preferido) o por IP (fallback).

    La API-Key se hashea para no almacenar el token en la tabla rate_limits.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return "ak:" + hashlib.sha256(api_key.encode()).hexdigest()[:16]
    # Fallback: IP del cliente (con cabecera de proxy si existe)
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = (
        forwarded.split(",")[0].strip()
        if forwarded
        else (request.client.host if request.client else "unknown")
    )
    return f"ip:{ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting global por cliente sobre la API REST.

    Usa :func:`db.rate_limits.check_rate_limit_db` como backend SQLite.
    Devuelve ``429 Too Many Requests`` con cabeceras estándar cuando se excede.

    Excluye paths configurables (e.g. ``/api/v1/health``) para no bloquear LBs.

    Args:
        app: Aplicación ASGI a envolver.
        max_calls: Máximo de requests permitidas en la ventana.
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
        rate_key = f"api:{client}:{path}"
        allowed = _check_rate_limit(
            rate_key,
            max_calls=self._max,
            window_seconds=self._window,
        )
        if not allowed:
            log.warning("rate_limit_exceeded", client=client, path=path)
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit excedido. Intenta de nuevo más tarde.",
                    "limit": self._max,
                    "window_seconds": self._window,
                },
                headers={
                    "Retry-After": str(int(self._window)),
                    "X-RateLimit-Limit": str(self._max),
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
                op = getattr(route, "path", None) or request.url.path.split("?")[0]
                api_cost_estimate_total.labels(operation=op).inc(int(usd * 1e6))
            except Exception:
                pass
        return response


# ───────────────────── Access log + métricas RED ──────────────────────────


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Access log estructurado y métricas RED (Rate, Errors, Duration) por endpoint.

    Registra por request:
    - método, path, status, duración en ms
    - key_hash_prefix (8 chars — para correlación sin exponer el token)
    - correlation_id (si está en contextvars)
    - client IP

    Publica métricas Prometheus:
    - ``http_requests_total{method, path, status}``
    - ``http_request_duration_seconds`` (histogram)
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
            key_prefix = (request.headers.get("X-API-Key") or "")[:8] or "-"
            client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
                request.client.host if request.client else "-"
            )

            log.info(
                "http_request",
                method=method,
                path=path,
                status=status_code,
                duration_ms=round(dt_ms, 1),
                key_prefix=key_prefix,
                client_ip=client_ip,
            )

            # Métricas Prometheus RED
            try:
                from observability.runtime_metrics import (
                    http_request_duration_seconds,
                    http_requests_total,
                )

                http_requests_total.labels(method=method, path=path, status=str(status_code)).inc()
                http_request_duration_seconds.labels(method=method, path=path).observe(dt_ms / 1000)
            except Exception:
                pass

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

                async def _passthrough(b: bytes = body) -> bytes:
                    return b

                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

        etag = 'W/"' + hashlib.sha1(body).hexdigest()[:24] + '"'  # noqa: S324 - sha1 for ETag only
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
