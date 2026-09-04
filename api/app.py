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
* ``GET /api/v1/exports/download``    — descarga síncrona CSV/Excel/PDF
* ``GET /metrics``                    — métricas Prometheus (scope metrics:read)

Los tres endpoints de export asíncrono (``POST /exports``, ``GET`` y
``DELETE /exports/{id}``) se retiraron el 2026-09-03; ver
``docs/rfc/2026-09-03-rfc-retirada-exports-asincronos.md``.

Arrancar el servidor::

    uvicorn api.app:app --host 0.0.0.0 --port 8080 --workers 2
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator as _PFI
from starlette.middleware.base import BaseHTTPMiddleware

from api.errors import register_exception_handlers
from api.middleware import (
    AccessLogMiddleware,
    CostTrackingMiddleware,
    ETagMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    _MaxBodyMiddleware,
    _RejectNulMiddleware,
    correlation_id_middleware,
)
from api.routes.admin_solicitudes import router as admin_solicitudes_router
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
from api.routes.metrics import router as metrics_router
from api.routes.models import router as models_router
from api.routes.notifications import router as notifications_router
from api.routes.organization_settings import router as organization_settings_router
from api.routes.predicciones import router as predicciones_router
from api.routes.publico import router as publico_router
from api.routes.publico_solicitudes import router as publico_solicitudes_router
from api.routes.pursuits import router as pursuits_router
from api.routes.radar import router as radar_router
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
      luego cierra el pool de conexiones Postgres limpiamente.
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

    # Dimensionar el threadpool de anyio, donde corre todo el trabajo síncrono.
    # El límite existe por CPU starvation en instancias de pocos vCPUs (Render
    # Free, 0.1 vCPU): sin él FastAPI despacha cada endpoint sync a un hilo
    # nuevo (default 40) y 9 peticiones Pandas concurrentes saturan el core.
    # Pero fijarlo en 4 castigaba también a las lecturas IO-bound, que solo
    # esperan red: el techo efectivo de la API pasaba a ser 4 peticiones
    # simultáneas contra un pool de conexiones más grande que eso. Quien tiene
    # que estar acotada es la carga CPU-bound, y para eso está su bulkhead
    # propio (``api.concurrency.run_cpu``), no el pool general.
    previous_tokens: float | None = None
    try:
        import anyio

        limiter = anyio.to_thread.current_default_thread_limiter()
        previous_tokens = limiter.total_tokens
        tokens = int(getattr(settings, "API_THREADPOOL_TOKENS", 24))
        limiter.total_tokens = tokens
        log.info("anyio_thread_limiter_set", max_threads=tokens, previous=previous_tokens)
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

    # Cerrar los pools de conexiones (escritura y lectura)
    try:
        from db.database import close_pool

        close_pool()
        log.info("api_shutdown_db_pool_closed")
    except Exception:
        pass

    # Restaurar el limiter global de anyio. Es estado de proceso, no de la app:
    # sin esto, la suite de tests que instancia la app con `with TestClient`
    # deja el threadpool encogido para todo lo que corra después.
    if previous_tokens is not None:
        try:
            import anyio

            anyio.to_thread.current_default_thread_limiter().total_tokens = previous_tokens
        except Exception:  # pragma: no cover - restauración best-effort
            log.debug("anyio_thread_limiter_restore_failed")


# ---------------------------------------------------------------------------
# Aplicación FastAPI
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Licitaciones SAP — API REST",
    description=(
        "API pública para consultar las licitaciones y adjudicaciones SAP "
        "extraídas de la Plataforma de Contratación del Sector Público (PLACSP).\n\n"
        "**Autenticación**: los endpoints protegidos declaran en OpenAPI si aceptan "
        "sesión, `X-API-Key` o ambas. `/publico/*`, `/health` y el inicio de sesión "
        "son anónimos por diseño.\n\n"
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
# CORS — orígenes permitidos (el middleware se monta en register_middlewares)
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

# ---------------------------------------------------------------------------
# Middlewares
# ---------------------------------------------------------------------------


def register_middlewares(target: FastAPI, *, cors_origins: list[str]) -> None:
    """Monta el stack de middlewares del más interno al más externo.

    ``add_middleware`` inserta al principio de la lista y el stack se construye
    tomando el primer elemento como el más externo: **el último añadido es el
    que ve la request primero**. Por eso este bloque se lee de dentro hacia
    fuera, al revés del orden de ejecución.

    El orden no es cosmético. ``RateLimitMiddleware`` y ``_MaxBodyMiddleware``
    cortocircuitan la petición y emiten 429/413 sin llegar al router; con CORS
    registrado el primero (es decir, el más interno) esas respuestas salían sin
    ``Access-Control-Allow-Origin`` ni cabeceras OWASP, y el SPA veía un error
    de red opaco en vez de un 429 accionable. CORS queda ahora el más externo y
    ``SecurityHeadersMiddleware`` por fuera de ambos cortocircuitos.

    Orden de ejecución resultante, de fuera hacia dentro::

        CORS → SecurityHeaders → CorrelationId → AccessLog → CostTracking
             → RateLimit → compresión → MaxBody → RejectNul → ETag → router
    """
    # ETag para respuestas GET JSON (cache condicional, F4)
    target.add_middleware(ETagMiddleware)

    # Byte NUL en path/query — un 400 honesto en vez del 500 que provocaba al
    # llegar a psycopg. Va por dentro de CORS/SecurityHeaders (igual que
    # _MaxBodyMiddleware) para que el cortocircuito salga con las cabeceras que
    # el SPA necesita.
    target.add_middleware(_RejectNulMiddleware)

    # Request body size limit — protege contra payloads abusivos (1 MB máx.)
    # Raw ASGI (evita el anti-patrón BaseHTTPMiddleware y el atributo privado _body).
    try:
        target.add_middleware(_MaxBodyMiddleware)
    except Exception:
        # Fail-loud (P4, 2026-05-24): la API arranca sin el límite, pero queda
        # constancia en el log en vez de degradarse en silencio.
        log.warning("max_body_middleware_unavailable", exc_info=True)

    # Compresión Brotli / GZip
    try:
        from brotli_asgi import BrotliMiddleware

        target.add_middleware(BrotliMiddleware, quality=4, minimum_size=1024)
        log.info("brotli_compression_enabled")
    except ImportError:
        from fastapi.middleware.gzip import GZipMiddleware

        target.add_middleware(GZipMiddleware, minimum_size=1024)
        log.info("gzip_compression_enabled_brotli_unavailable")

    # Rate limiting por IP
    target.add_middleware(
        RateLimitMiddleware,
        max_calls=int(getattr(settings, "API_RATE_LIMIT_MAX_CALLS", 120)),
        window_seconds=float(getattr(settings, "API_RATE_LIMIT_WINDOW_SECONDS", 60)),
    )

    # Cost tracking — métrica Prometheus por endpoint
    target.add_middleware(CostTrackingMiddleware)

    # Access log estructurado (request/response)
    target.add_middleware(AccessLogMiddleware)

    # Correlation-ID: por fuera del rate limit para que un 429 también sea
    # correlacionable con su entrada de log.
    target.add_middleware(BaseHTTPMiddleware, dispatch=correlation_id_middleware)

    # Security headers OWASP — por fuera de todo lo que puede cortocircuitar.
    target.add_middleware(SecurityHeadersMiddleware)

    # CORS el más externo: sus cabeceras deben acompañar a cualquier respuesta,
    # incluidas las que genera el propio stack de middlewares.
    target.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
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


register_middlewares(app, cors_origins=_cors_origins)

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
# Superficie pública anónima. Cuelga de /api/v1/publico y no de
# /api/v1/licitaciones porque el catch-all autenticado del final de este
# fichero ensombrecería cualquier ruta pública bajo ese prefijo, y le
# devolvería 401 a los rastreadores sin fallar en el arranque.
app.include_router(publico_router, prefix="/api/v1")
# Único endpoint público de escritura: la cola de solicitudes de acceso que
# alimenta el formulario de la landing. Mismo prefijo y mismo motivo.
app.include_router(publico_solicitudes_router, prefix="/api/v1")
app.include_router(pursuits_router, prefix="/api/v1")
app.include_router(organization_settings_router, prefix="/api/v1")
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
app.include_router(radar_router, prefix="/api/v1")
app.include_router(saved_filters_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(admin_users_router, prefix="/api/v1")
app.include_router(admin_solicitudes_router, prefix="/api/v1")
app.include_router(feature_flags_router, prefix="/api/v1")
app.include_router(ask_router, prefix="/api/v1")
# Sin prefijo /api/v1: `GET /metrics` es la ruta que Prometheus ya scrapea y
# la que declaran los dashboards y el render.yaml. Su auth y su formato de
# exposición viven en `api/routes/metrics.py`.
app.include_router(metrics_router)


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
