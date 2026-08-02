"""API REST FastAPI — punto de entrada.

Expone los endpoints bajo ``/api/v1/``:

* ``GET /api/v1/health``              — sin auth — estado del servicio
* ``GET /api/v1/health/live``         — liveness probe (proceso vivo)
* ``GET /api/v1/health/ready``        — readiness probe (DB + deps listas)
* ``GET /api/v1/licitaciones``        — requiere X-API-Key — listado paginado
* ``GET /api/v1/licitaciones/{id}``   — requiere X-API-Key — detalle
* ``GET /api/v1/licitaciones/cursor`` — paginación por cursor
* ``POST /api/v1/licitaciones/search``— búsqueda avanzada
* ``GET /api/v1/adjudicaciones``      — requiere X-API-Key — listado paginado
* ``GET /api/v1/meta/filters``        — opciones válidas para filtros
* ``POST /api/v1/feedback``           — requiere X-API-Key
* ``POST|GET|DELETE /api/v1/webhooks``— requiere X-API-Key + scope
* ``GET|DELETE /api/v1/me``           — GDPR
* ``POST /api/v1/exports``            — requiere X-API-Key — crea job PDF async
* ``GET /api/v1/exports/{id}``        — requiere X-API-Key — descarga PDF

Arrancar el servidor::

    uvicorn api.app:app --host 0.0.0.0 --port 8080 --workers 2
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator as _PFI
from structlog.contextvars import bind_contextvars, clear_contextvars

from api.errors import register_exception_handlers
from api.middleware import (
    AccessLogMiddleware,
    CostTrackingMiddleware,
    ETagMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    _trusted_client_ip,
)
from api.routes.admin_users import router as admin_users_router
from api.routes.analytics import router as analytics_router
from api.routes.ask import router as ask_router
from api.routes.auth import router as auth_router
from api.routes.competitive import router as competitive_router
from api.routes.empresas import router as empresas_router
from api.routes.eventos import router as eventos_router
from api.routes.exports import router as exports_router
from api.routes.feature_flags import router as feature_flags_router
from api.routes.feedback import router as feedback_router
from api.routes.health import router as health_router
from api.routes.licitaciones import get_licitacion as _get_licitacion_handler
from api.routes.licitaciones import router as licitaciones_router
from api.routes.me import router as me_router
from api.routes.meta import router as meta_router
from api.routes.models import router as models_router
from api.routes.notifications import router as notifications_router
from api.routes.predicciones import router as predicciones_router
from api.routes.pursuits import router as pursuits_router
from api.routes.resoluciones import router as resoluciones_router
from api.routes.saved_filters import router as saved_filters_router
from api.routes.search import router as search_router
from api.routes.security import router as security_router
from api.routes.stream import router as stream_router
from api.routes.watchlist_feed import router as watchlist_feed_router
from api.routes.watchlist_items import router as watchlist_items_router
from api.routes.watchlist_rules import router as watchlist_rules_router
from api.routes.webhooks import router as webhooks_router
from config import settings
from db.database import init_db
from observability import configure_logging, configure_sentry, configure_tracing
from observability.logging import get_logger

log = get_logger(__name__)

# Logging estructurado y tracing (idempotente)
configure_logging()
configure_tracing(service_name="licitaciones-api")
configure_sentry(service="licitaciones-api")


# ---------------------------------------------------------------------------
# Lifespan (reemplaza @on_event("startup") — FastAPI ≥0.93)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Inicializa la DB al arrancar y hace graceful shutdown al parar.

    - Startup: ejecuta migraciones y crea tablas. Falla rápido en prod si hay error.
    - Shutdown: espera hasta 30s a que los BackgroundTasks en vuelo terminen,
      luego cierra el pool de conexiones SQLite limpiamente.
    """
    import asyncio

    # Startup
    try:
        init_db()
        log.info("api_startup_ok")
    except Exception as exc:
        log.error("api_startup_db_error", error=str(exc))
        raise  # fail fast en todos los entornos

    # Exponer el set de pending tasks en app.state para que middlewares puedan registrarlas
    app.state.pending_background_tasks = set()

    # No precalentar las cachés analíticas full-table durante el startup. En el
    # incidente de Render del 2026-08-02, estas dos cargas sin límite
    # (licitaciones como DataFrame y adjudicaciones como list[dict]) agotaban
    # los 2 GiB del contenedor antes de emitir ``api_prewarm_done`` y dejaban el
    # servicio en un bucle de reinicios. Los endpoints analíticos conservan la
    # carga lazy mientras sus agregados se migran a SQL (backlog P1).
    log.info("analytics_full_table_prewarm_disabled")

    # Limitar hilos del threadpool de anyio — evita CPU starvation en instancias
    # con pocos vCPUs (ej. Render Free 0.1 vCPU).  Sin este límite, FastAPI
    # despacha cada endpoint sync a un hilo nuevo (default 40), provocando que
    # 9 peticiones Pandas concurrentes saturen el único core y generen 502.
    try:
        import anyio

        anyio.to_thread.current_default_thread_limiter().total_tokens = 4
        log.info("anyio_thread_limiter_set", max_threads=4)
    except Exception as exc:
        log.warning("anyio_thread_limiter_failed", error=str(exc))

    yield

    # Shutdown — drenar background tasks primero
    pending: set[asyncio.Task[object]] = getattr(app.state, "pending_background_tasks", set())
    if pending:
        log.info("api_shutdown_draining_tasks", count=len(pending))
        try:
            _done, still_running = await asyncio.wait(pending, timeout=30.0)
            if still_running:
                log.warning(
                    "api_shutdown_tasks_abandoned",
                    abandoned=len(still_running),
                )
                for task in still_running:
                    task.cancel()
        except Exception as exc:
            log.warning("api_shutdown_drain_error", error=str(exc))

    # Cerrar pool de conexiones SQLite
    try:
        from db.database import close_pool

        close_pool()
        log.info("api_shutdown_db_pool_closed")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Aplicación FastAPI
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Licitaciones SAP — API REST",
    description=(
        "API pública para consultar las licitaciones y adjudicaciones SAP "
        "extraídas de la Plataforma de Contratación del Sector Público (PLACSP).\n\n"
        "**Autenticación**: cabecera `X-API-Key` en todos los endpoints excepto `/health`.\n\n"
        "**Rate limiting**: 120 req/min por API-Key (configurable). Devuelve 429 al exceder.\n\n"
        "**Trazabilidad**: cada request acepta y devuelve `X-Correlation-Id` para "
        "correlación end-to-end con los logs.\n\n"
        "**Errores**: respuestas en formato [RFC 7807](https://datatracker.ietf.org/doc/html/rfc7807) "
        "(`application/problem+json`)."
    ),
    version="2.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    openapi_tags=[
        {"name": "health", "description": "Health checks (sin autenticación)"},
        {"name": "auth", "description": "Session auth (login, logout, OAuth, me)"},
        {"name": "licitaciones", "description": "Consulta de licitaciones y adjudicaciones"},
        {
            "name": "analytics",
            "description": "Aggregated analytics: overview, trends, geography, competitors, scoring, quality",
        },
        {"name": "feedback", "description": "Feedback de relevancia para active learning"},
        {"name": "webhooks", "description": "Suscripciones a notificaciones de watchlist"},
        {"name": "meta", "description": "Metadatos: valores válidos para filtros"},
        {
            "name": "models",
            "description": "Model registry: versiones activas, histórico, activación",
        },
        {"name": "me", "description": "GDPR: exportar y eliminar mis datos"},
        {
            "name": "ask",
            "description": "RAG + LLM: preguntas en lenguaje natural sobre licitaciones",
        },
    ],
    contact={
        "name": "licitaciones-sap maintainers",
        "url": "https://github.com/danielkalitovics/licitaciones-sap",
    },
    license_info={"name": "MIT"},
    lifespan=lifespan,
)

# Registrar exception handlers RFC 7807
register_exception_handlers(app)

# Prometheus auto-instrumentación HTTP — métricas RED estándar por handler
# (prometheus-fastapi-instrumentator es dependencia hard; no usar try/except aquí)
_PFI(
    should_group_status_codes=False,
    excluded_handlers=[r"/api/v1/health.*", r"/metrics"],
).instrument(app)
log.info("prometheus_fastapi_instrumentator_enabled")

# OpenTelemetry auto-instrumentación HTTP (solo si OTEL_EXPORTER_OTLP_ENDPOINT está configurado)
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls="health.*,metrics",
        )
        log.info("otel_fastapi_instrumentor_enabled")
    else:
        log.debug("otel_fastapi_instrumentor_skipped", reason="OTEL_EXPORTER_OTLP_ENDPOINT_not_set")
except ImportError:
    log.debug("otel_fastapi_instrumentor_unavailable")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

_cors_origins: list[str]
if settings.CORS_ALLOWED_ORIGINS:
    _cors_origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
elif settings.ENV in ("prod", "staging"):
    _cors_origins = []
    log.warning(
        "cors_no_origins_configured",
        env=settings.ENV,
        hint="CORS_ALLOWED_ORIGINS is empty — no cross-origin requests will be allowed.",
    )
else:
    # Desarrollo local explícito: no usar wildcard con cookies de sesión.
    _cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
    log.info("cors_local_origins_enabled", env=settings.ENV, origins=_cors_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=[
        "X-API-Key",
        "X-Correlation-Id",
        "X-CSRF-Token",
        "Idempotency-Key",
        "Content-Type",
        "Accept",
        "Authorization",
    ],
)

# ---------------------------------------------------------------------------
# Middlewares (se añaden en orden inverso de ejecución)
# ---------------------------------------------------------------------------

# Security headers OWASP
app.add_middleware(SecurityHeadersMiddleware)

# ETag para respuestas GET JSON (cache condicional, F4)
app.add_middleware(ETagMiddleware)

# Request body size limit — protege contra payloads abusivos (1 MB máx.)
# Raw ASGI middleware (evita anti-pattern BaseHTTPMiddleware y atributo privado _body).
try:
    from starlette.types import ASGIApp as _ASGIApp
    from starlette.types import Receive as _Receive
    from starlette.types import Scope as _Scope
    from starlette.types import Send as _Send

    class _MaxBodyMiddleware:
        """Rechaza requests con body > 1 MB usando raw ASGI.

        Comprueba Content-Length (fast path) y acumula tamaño en streaming
        (slow path) sin buffering completo del body.
        """

        _MAX_BYTES = 1 * 1024 * 1024  # 1 MB
        _413_BODY = b'{"detail":"Request body demasiado grande (m\\u00e1x. 1 MB)."}'

        def __init__(self, app: _ASGIApp) -> None:
            self.app = app

        async def __call__(self, scope: _Scope, receive: _Receive, send: _Send) -> None:
            if scope["type"] != "http":
                await self.app(scope, receive, send)
                return

            # Fast path: rechazar inmediatamente si Content-Length lo delata
            headers = dict(scope.get("headers") or [])
            cl_raw = headers.get(b"content-length")
            if cl_raw is not None:
                try:
                    if int(cl_raw) > self._MAX_BYTES:
                        await self._send_413(send)
                        return
                except (ValueError, UnicodeDecodeError):
                    pass

            # Slow path: para requests con body, envolver receive para contar bytes
            method = scope.get("method", "")
            if method in ("POST", "PUT", "PATCH"):
                body_size = 0
                max_bytes = self._MAX_BYTES

                async def limiting_receive() -> dict:  # type: ignore[type-arg]
                    nonlocal body_size
                    message = await receive()
                    if message.get("type") == "http.request":
                        body_size += len(message.get("body", b""))
                        if body_size > max_bytes:
                            raise _BodyTooLargeError
                    return dict(message)

                try:
                    await self.app(scope, limiting_receive, send)
                except _BodyTooLargeError:
                    await self._send_413(send)
            else:
                await self.app(scope, receive, send)

        async def _send_413(self, send: _Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 413,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"content-length", str(len(self._413_BODY)).encode()],
                    ],
                }
            )
            await send({"type": "http.response.body", "body": self._413_BODY})

    class _BodyTooLargeError(Exception):
        """Señal interna para abortar el pipeline cuando el body excede el límite."""

    app.add_middleware(_MaxBodyMiddleware)
except Exception:
    log.warning("max_body_middleware_unavailable", exc_info=True)

# Compresión Brotli / GZip
try:
    from brotli_asgi import BrotliMiddleware

    app.add_middleware(BrotliMiddleware, quality=4, minimum_size=1024)
    log.info("brotli_compression_enabled")
except ImportError:
    from fastapi.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    log.info("gzip_compression_enabled_brotli_unavailable")

# Rate limiting per-API-Key
app.add_middleware(
    RateLimitMiddleware,
    max_calls=int(getattr(settings, "API_RATE_LIMIT_MAX_CALLS", 120)),
    window_seconds=float(getattr(settings, "API_RATE_LIMIT_WINDOW_SECONDS", 60)),
)

# Cost tracking — métrica Prometheus por endpoint
app.add_middleware(CostTrackingMiddleware)

# Access log estructurado (request/response)
app.add_middleware(AccessLogMiddleware)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(
    stream_router, prefix="/api/v1"
)  # antes de licitaciones (evita colisión con {id})
app.include_router(licitaciones_router, prefix="/api/v1")
app.include_router(empresas_router, prefix="/api/v1")
app.include_router(competitive_router, prefix="/api/v1")
app.include_router(eventos_router, prefix="/api/v1")
app.include_router(resoluciones_router, prefix="/api/v1")
app.include_router(predicciones_router, prefix="/api/v1")
app.include_router(pursuits_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(meta_router, prefix="/api/v1")
app.include_router(models_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(security_router, prefix="/api/v1")
app.include_router(watchlist_feed_router, prefix="/api/v1")
app.include_router(watchlist_rules_router, prefix="/api/v1")
app.include_router(watchlist_items_router, prefix="/api/v1")
app.include_router(exports_router, prefix="/api/v1")
app.include_router(saved_filters_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(admin_users_router, prefix="/api/v1")
app.include_router(feature_flags_router, prefix="/api/v1")
app.include_router(ask_router, prefix="/api/v1")


# ---------------------------------------------------------------------------
# Root endpoint — evita 404 en health probes de plataforma (HEAD/GET /)
# ---------------------------------------------------------------------------


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def _root() -> dict[str, str]:
    """Endpoint raíz para probes de plataforma que golpean ``/``.

    Cubre tanto ``GET /`` como ``HEAD /`` (health checks que solo verifican el
    código de estado). La API vive bajo ``/api/v1``; aquí solo devolvemos
    metadatos de descubrimiento.
    """
    return {
        "service": "licitaciones-sap-api",
        "status": "ok",
        "docs": "/api/docs",
        "health": "/api/v1/health",
    }


# ---------------------------------------------------------------------------
# Fallback detalle — ids con '/' (p.ej. "PA-S 2026/000058")
# ---------------------------------------------------------------------------
# La ruta /api/v1/licitaciones/{id_externo} usa el conversor por defecto
# ([^/]+), que no admite barras. Como algunos id_externo contienen '/',
# registramos un catch-all con el conversor ``:path`` que reutiliza el mismo
# handler. Va al final (último globalmente) para no ensombrecer las sub-rutas
# específicas (/explain, /tech-scores, /eventos, /prediccion-baja).
app.add_api_route(
    "/api/v1/licitaciones/{id_externo:path}",
    _get_licitacion_handler,
    methods=["GET"],
    include_in_schema=False,
)


# ---------------------------------------------------------------------------
# Prometheus /metrics — protegido por IP allowlist o scope metrics:read
# ---------------------------------------------------------------------------

try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    from observability.prometheus import _prometheus_available

    if _prometheus_available():

        @app.get("/metrics", include_in_schema=False)
        def _prometheus_metrics(request: Request) -> Response:
            """Expone métricas Prometheus. Protegido por X-API-Key + IP allowlist.

            Seguridad: en entornos Docker la IP del cliente puede ser la del
            gateway de la red interna, no 127.0.0.1. Por eso se requiere API
            key con scope ``metrics:read`` siempre que el ENV no sea ``dev``.
            En dev, el IP allowlist basta para acceso local sin key.
            """
            _metrics_allowed_ips: set[str] = set(
                ip.strip() for ip in settings.METRICS_ALLOWED_IPS.split(",") if ip.strip()
            )
            client_ip = _trusted_client_ip(request)
            ip_allowed = client_ip in _metrics_allowed_ips

            api_key_raw = request.headers.get("X-API-Key")
            key_authenticated = False
            if api_key_raw:
                from api.auth import hash_api_key
                from db.connection import now_utc_iso
                from services import auth as auth_service

                key_hash = hash_api_key(api_key_raw)
                record = auth_service.lookup_active_key(key_hash)
                scopes = record.scopes if record is not None else ""
                scope_set = frozenset(scope.strip() for scope in scopes.split(",") if scope.strip())
                is_bound = record is not None and record.user_id is not None
                is_unexpired = record is not None and (
                    record.expires_at is None or now_utc_iso() <= record.expires_at
                )
                if (
                    is_unexpired
                    and (settings.ENV == "dev" or is_bound)
                    and ("*" in scope_set or "metrics:read" in scope_set)
                ):
                    key_authenticated = True

            # En prod/staging: requiere API key siempre (IP allowlist es condición adicional, no suficiente)
            if settings.ENV in ("prod", "staging"):
                if not key_authenticated:
                    return Response(status_code=401, content="Unauthorized")
            else:
                # En dev: basta con IP allowlist O API key
                if not ip_allowed and not key_authenticated:
                    return Response(status_code=401, content="Unauthorized")

            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

        log.info("prometheus_metrics_endpoint_enabled", path="/metrics")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Middleware: Correlation-ID end-to-end
# ---------------------------------------------------------------------------


@app.middleware("http")
async def correlation_id_middleware(
    request: Request,
    call_next: object,
) -> Response:
    """Propaga X-Correlation-Id entre cliente, logs y respuesta."""
    from collections.abc import Awaitable
    from collections.abc import Callable as _Callable

    correlation_id = request.headers.get("X-Correlation-Id") or str(uuid.uuid4())

    # Limpiar y bindear variables de contexto structlog para esta request
    clear_contextvars()
    bind_contextvars(correlation_id=correlation_id)

    next_fn: _Callable[[Request], Awaitable[Response]] = call_next  # type: ignore[assignment]
    response = await next_fn(request)

    response.headers["X-Correlation-Id"] = correlation_id
    return response
