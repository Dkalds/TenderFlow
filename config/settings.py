"""Configuración global del proyecto — basada en pydantic-settings.

``Settings`` compone un mixin por dominio (P3 «Los dos módulos-dios»); cada uno
vive en su módulo hermano ``config/settings_<dominio>.py`` con sus campos y sus
validadores:

- ``entorno``: ``ENV``, ``APP_PROFILE``, rutas y las propiedades de gating.
- ``bd``: Postgres (DSN, TLS, pools, timeouts) y ``database_admin_url``.
- ``auth``: OAuth, sesiones, MFA, API keys y claves de firma.
- ``api``: CORS, límites, bulkheads, IP del cliente y Redis.
- ``correo``: alertas SMTP y correo transaccional.
- ``observabilidad``: OpenTelemetry, logs, latido, Grafana y anomalías.
- ``scraper``: ingesta, allowlists de salida y conectores.
- ``pliegos``: embeddings, RAG, ficha tipada y lotes del job nocturno.
- ``llm``: carriles LLM y presupuesto de gasto.
- ``ml``: clasificadores y modelos predictivos.
- ``analitica``: scoring y competidores.
- ``retencion``: plazos de purga.
- ``resumen``, ``embeddings``, ``object_store``: resumen pre-generado,
  codificador ONNX y almacén de objetos.
- ``mcp`` y ``cola``: funciones de entorno (no campos) del servidor MCP y de
  la cola de trabajo y el outbox.

El contrato no cambia: mismas variables de entorno, mismos defaults y
validadores, y ``from config.settings import …`` sirve todo lo de antes (lo
fija ``tests/test_config_settings_contrato.py``). Un setting **nuevo** va al
mixin de su dominio, no a este fichero. ``model_config`` vive solo aquí: los
mixins no lo declaran para que no puedan divergir.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from config.settings_analitica import AnaliticaSettings
from config.settings_api import ApiSettings, _origen_cors_seguro, _redis_publico_sin_tls
from config.settings_auth import (
    LONGITUD_MINIMA_CLAVE,
    AuthSettings,
    oauth_microsoft_client_id,
    oauth_microsoft_client_secret,
    oauth_microsoft_tenant,
)
from config.settings_bd import (
    _ADMIN_DB_URL_ENV,
    _PERFIL_POR_DEFECTO,
    _PERFILES_CON_CREDENCIAL_ADMIN,
    BaseDatosSettings,
    database_admin_url,
)
from config.settings_cola import (
    EVENT_DISPATCH_MAX_AGE_HOURS_DEFAULT,
    JOBS_BACKOFF_BASE_SEGUNDOS_DEFAULT,
    JOBS_EXPORT_UMBRAL_FILAS_DEFAULT,
    JOBS_LOCK_TTL_SEGUNDOS_DEFAULT,
    JOBS_MAX_INTENTOS_DEFAULT,
    JOBS_WORKER_POLL_SEGUNDOS_DEFAULT,
    event_dispatch_enabled,
    event_dispatch_max_age_hours,
    jobs_backoff_base_segundos,
    jobs_cierre_por_cola,
    jobs_consumidor_en_api,
    jobs_export_umbral_filas,
    jobs_lock_ttl_segundos,
    jobs_max_intentos,
    jobs_worker_poll_segundos,
)
from config.settings_correo import CorreoSettings
from config.settings_embeddings import EmbeddingsOnnxSettings
from config.settings_entorno import _ROOT
from config.settings_llm import LlmSettings
from config.settings_mcp import (
    mcp_database_ssl_problema,
    mcp_database_url,
    mcp_google_redirect_uri,
    mcp_public_url,
    mcp_redirect_uris_extra,
)
from config.settings_ml import MLSettings
from config.settings_object_store import ObjectStoreSettings
from config.settings_observabilidad import ObservabilidadSettings
from config.settings_pliegos import PliegosSettings
from config.settings_resumen import ResumenPregenSettings
from config.settings_retencion import RetencionSettings
from config.settings_scraper import ScraperSettings

__all__ = [
    "EVENT_DISPATCH_MAX_AGE_HOURS_DEFAULT",
    "JOBS_BACKOFF_BASE_SEGUNDOS_DEFAULT",
    "JOBS_EXPORT_UMBRAL_FILAS_DEFAULT",
    "JOBS_LOCK_TTL_SEGUNDOS_DEFAULT",
    "JOBS_MAX_INTENTOS_DEFAULT",
    "JOBS_WORKER_POLL_SEGUNDOS_DEFAULT",
    "LONGITUD_MINIMA_CLAVE",
    "_ADMIN_DB_URL_ENV",
    "_PERFILES_CON_CREDENCIAL_ADMIN",
    "_PERFIL_POR_DEFECTO",
    "_ROOT",
    "Settings",
    "_origen_cors_seguro",
    "_redis_publico_sin_tls",
    "database_admin_url",
    "ensure_data_dirs",
    "event_dispatch_enabled",
    "event_dispatch_max_age_hours",
    "jobs_backoff_base_segundos",
    "jobs_cierre_por_cola",
    "jobs_consumidor_en_api",
    "jobs_export_umbral_filas",
    "jobs_lock_ttl_segundos",
    "jobs_max_intentos",
    "jobs_worker_poll_segundos",
    "mcp_database_ssl_problema",
    "mcp_database_url",
    "mcp_google_redirect_uri",
    "mcp_public_url",
    "mcp_redirect_uris_extra",
    "oauth_microsoft_client_id",
    "oauth_microsoft_client_secret",
    "oauth_microsoft_tenant",
    "settings",
]


# El orden de las bases fija el de los `model_validator`: pydantic los ejecuta
# recorriendo el MRO al revés, así que corren primero los de la última base. Este
# orden deja delante los que derivan valores (rutas, timeouts, pools) y, de los
# que rechazan, los de BD y auth, como en el fichero único: cuando fallan varios,
# el error que sale primero es el de la credencial.
class Settings(
    ResumenPregenSettings,
    EmbeddingsOnnxSettings,
    ObjectStoreSettings,
    CorreoSettings,
    ObservabilidadSettings,
    ApiSettings,
    ScraperSettings,
    AuthSettings,
    BaseDatosSettings,
    PliegosSettings,
    LlmSettings,
    MLSettings,
    AnaliticaSettings,
    RetencionSettings,
    BaseSettings,
):
    """Todas las variables de entorno del proyecto, validadas al arrancar."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def _load() -> Settings:
    return Settings()


_settings = _load()

# ── Singleton accesible para nuevos consumidores ─────────────────────────
# Uso recomendado: ``from config import settings`` y luego ``settings.DATA_DIR``.
settings = _settings


def ensure_data_dirs() -> None:
    """Crea los directorios de datos si no existen."""
    _settings.DATA_DIR.mkdir(exist_ok=True)
    downloads = _settings.DOWNLOADS_DIR
    if downloads is not None:
        downloads.mkdir(exist_ok=True)
