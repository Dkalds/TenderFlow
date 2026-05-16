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

Arrancar el servidor::

    uvicorn api.app:app --host 0.0.0.0 --port 8080 --workers 2
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

from api.errors import register_exception_handlers
from api.middleware import (
    AccessLogMiddleware,
    CostTrackingMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)
from api.routes.feedback import router as feedback_router
from api.routes.health import router as health_router
from api.routes.licitaciones import router as licitaciones_router
from api.routes.me import router as me_router
from api.routes.meta import router as meta_router
from api.routes.security import router as security_router
from api.routes.webhooks import router as webhooks_router
from config import settings
from db.database import init_db
from observability import configure_logging, configure_tracing
from observability.logging import get_logger

log = get_logger(__name__)

# Logging estructurado y tracing (idempotente)
configure_logging()
configure_tracing(service_name="licitaciones-api")


# ---------------------------------------------------------------------------
# Lifespan (reemplaza @on_event("startup") — FastAPI ≥0.93)
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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
        if settings.ENV == "prod":
            raise  # fail fast en producción

    # Exponer el set de pending tasks en app.state para que middlewares puedan registrarlas
    app.state.pending_background_tasks: set[asyncio.Task] = set()

    yield

    # Shutdown — drenar background tasks primero
    pending = getattr(app.state, "pending_background_tasks", set())
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
        {"name": "licitaciones", "description": "Consulta de licitaciones y adjudicaciones"},
        {"name": "feedback", "description": "Feedback de relevancia para active learning"},
        {"name": "webhooks", "description": "Suscripciones a notificaciones de watchlist"},
        {"name": "meta", "description": "Metadatos: valores válidos para filtros"},
        {"name": "me", "description": "GDPR: exportar y eliminar mis datos"},
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

# OpenTelemetry auto-instrumentación HTTP (no-op si OTEL_EXPORTER_OTLP_ENDPOINT vacío)
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health.*,metrics",
    )
    log.info("otel_fastapi_instrumentor_enabled")
except ImportError:
    log.debug("otel_fastapi_instrumentor_unavailable")

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

_cors_origins: list[str]
if settings.ENV == "dev":
    _cors_origins = ["*"]
elif settings.CORS_ALLOWED_ORIGINS:
    _cors_origins = [o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
else:
    _cors_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    allow_headers=[
        "X-API-Key",
        "X-Correlation-Id",
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
app.include_router(licitaciones_router, prefix="/api/v1")
app.include_router(feedback_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(meta_router, prefix="/api/v1")
app.include_router(security_router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Prometheus /metrics — protegido por IP allowlist o scope metrics:read
# ---------------------------------------------------------------------------

try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    from observability.prometheus import _prometheus_available

    if _prometheus_available():

        @app.get("/metrics", include_in_schema=False)
        def _prometheus_metrics(request: Request) -> Response:
            """Expone métricas Prometheus. Protegido por X-API-Key o IP allowlist."""
            # IP allowlist (para scrapers internos / Prometheus server)
            _metrics_allowed_ips: set[str] = set(
                ip.strip() for ip in settings.METRICS_ALLOWED_IPS.split(",") if ip.strip()
            )
            client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or (
                request.client.host if request.client else ""
            )
            if client_ip not in _metrics_allowed_ips:
                # Requiere API key con scope metrics:read
                api_key_raw = request.headers.get("X-API-Key")
                if not api_key_raw:
                    return Response(status_code=401, content="Unauthorized")
                # Validación síncrona mínima (endpoint no async)
                from api.auth import hash_api_key
                from db.database import connect_read

                key_hash = hash_api_key(api_key_raw)
                try:
                    with connect_read() as c:
                        row = c.execute(
                            "SELECT scopes FROM api_keys WHERE key_hash = ? AND is_active = 1",
                            (key_hash,),
                        ).fetchone()
                    if not row:
                        return Response(status_code=401, content="Unauthorized")
                    scopes = str(row[0] or "*")
                    if "*" not in scopes and "metrics:read" not in scopes:
                        return Response(status_code=403, content="Forbidden")
                except Exception:
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
