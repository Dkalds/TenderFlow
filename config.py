"""Configuración global del proyecto — basada en pydantic-settings."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).parent


class Settings(BaseSettings):
    """Todas las variables de entorno del proyecto, validadas al arrancar."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Entorno ──────────────────────────────────────────────────────────
    ENV: Literal["dev", "prod"] = "dev"

    # ── Rutas ────────────────────────────────────────────────────────────
    DATA_DIR: Path = _ROOT / "data"
    DB_PATH: Path | None = None  # default calculado en validator
    DOWNLOADS_DIR: Path | None = None

    # ── Dashboard ────────────────────────────────────────────────────────
    DASHBOARD_PASSWORD: str = ""
    DASHBOARD_CACHE_TTL: int = 300

    # ── OAuth ────────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    OAUTH_REDIRECT_URI: str = "http://localhost:8501"

    # ── Turso ────────────────────────────────────────────────────────────
    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: str = ""
    TURSO_LOCAL_DB: Path | None = None

    # ── Observabilidad ───────────────────────────────────────────────────
    LOG_FORMAT: str = ""
    ALERT_MIN_LEVEL: str = "warn"
    ALERT_EMAIL_TO: str = ""
    ALERT_SMTP_USER: str = ""
    ALERT_SMTP_PASSWORD: str = ""
    ALERT_SMTP_HOST: str = "smtp.gmail.com"
    ALERT_SMTP_PORT: int = 587

    # ── Scraper ──────────────────────────────────────────────────────────
    REQUEST_TIMEOUT: int = 30
    REQUEST_DELAY_SECONDS: float = 1.5
    MAX_DOWNLOAD_SIZE_BYTES: int = 200 * 1024 * 1024
    MAX_XML_SIZE_BYTES: int = 150 * 1024 * 1024
    DAILY_MAX_PAGES: int = 50
    BACKFILL_MAX_WORKERS: int = 3

    # ── Validators ───────────────────────────────────────────────────────
    @model_validator(mode="after")
    def _set_derived_paths(self) -> Settings:
        if self.DB_PATH is None:
            self.DB_PATH = self.DATA_DIR / "licitaciones.db"
        if self.DOWNLOADS_DIR is None:
            self.DOWNLOADS_DIR = self.DATA_DIR / "downloads"
        if self.TURSO_LOCAL_DB is None:
            self.TURSO_LOCAL_DB = self.DATA_DIR / "licitaciones_replica.db"
        return self

    @model_validator(mode="after")
    def _validate_turso_pair(self) -> Settings:
        if bool(self.TURSO_DATABASE_URL) ^ bool(self.TURSO_AUTH_TOKEN):
            warnings.warn(
                "Configuración Turso incompleta: se necesitan TURSO_DATABASE_URL y "
                "TURSO_AUTH_TOKEN juntas. Se usará SQLite local como fallback.",
                stacklevel=2,
            )
            self.TURSO_DATABASE_URL = ""
            self.TURSO_AUTH_TOKEN = ""
        return self

    @model_validator(mode="after")
    def _validate_prod_password(self) -> Settings:
        if self.ENV == "prod" and not self.DASHBOARD_PASSWORD:
            raise ValueError(
                "DASHBOARD_PASSWORD es obligatorio en ENV=prod. "
                "Configura la variable de entorno antes de arrancar."
            )
        return self

    @field_validator("DASHBOARD_CACHE_TTL", mode="before")
    @classmethod
    def _parse_cache_ttl(cls, v: object) -> int:
        return int(v)  # type: ignore[arg-type]


def _load() -> Settings:
    return Settings()  # type: ignore[call-arg]


_settings = _load()

# ── Singleton accesible para nuevos consumidores ─────────────────────────
# Uso recomendado: ``from config import settings`` y luego ``settings.DB_PATH``.
settings = _settings

# ── Backward-compatible module-level exports ─────────────────────────────
# DEPRECADO: usar ``settings.X`` en lugar de ``from config import X``.
# Estos aliases se mantienen temporalmente para no romper consumidores existentes.
ROOT = _ROOT
DATA_DIR = _settings.DATA_DIR
DOWNLOADS_DIR = _settings.DOWNLOADS_DIR  # type: ignore[assignment]
DB_PATH = _settings.DB_PATH  # type: ignore[assignment]
DASHBOARD_PASSWORD = _settings.DASHBOARD_PASSWORD
DASHBOARD_CACHE_TTL = _settings.DASHBOARD_CACHE_TTL
GOOGLE_CLIENT_ID = _settings.GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET = _settings.GOOGLE_CLIENT_SECRET
OAUTH_REDIRECT_URI = _settings.OAUTH_REDIRECT_URI
TURSO_DATABASE_URL = _settings.TURSO_DATABASE_URL
TURSO_AUTH_TOKEN = _settings.TURSO_AUTH_TOKEN
TURSO_LOCAL_DB = _settings.TURSO_LOCAL_DB  # type: ignore[assignment]
LOG_FORMAT = _settings.LOG_FORMAT
ALERT_MIN_LEVEL = _settings.ALERT_MIN_LEVEL
ALERT_EMAIL_TO = _settings.ALERT_EMAIL_TO
ALERT_SMTP_USER = _settings.ALERT_SMTP_USER
ALERT_SMTP_PASSWORD = _settings.ALERT_SMTP_PASSWORD
ALERT_SMTP_HOST = _settings.ALERT_SMTP_HOST
ALERT_SMTP_PORT = _settings.ALERT_SMTP_PORT
REQUEST_TIMEOUT = _settings.REQUEST_TIMEOUT
REQUEST_DELAY_SECONDS = _settings.REQUEST_DELAY_SECONDS
MAX_DOWNLOAD_SIZE_BYTES = _settings.MAX_DOWNLOAD_SIZE_BYTES
MAX_XML_SIZE_BYTES = _settings.MAX_XML_SIZE_BYTES
DAILY_MAX_PAGES = _settings.DAILY_MAX_PAGES
BACKFILL_MAX_WORKERS = _settings.BACKFILL_MAX_WORKERS


def ensure_data_dirs() -> None:
    """Crea los directorios de datos si no existen."""
    DATA_DIR.mkdir(exist_ok=True)
    DOWNLOADS_DIR.mkdir(exist_ok=True)


# Palabras clave para filtrar licitaciones SAP
SAP_KEYWORDS = [
    # Plataforma principal
    "sap",
    "s/4hana",
    "s4hana",
    "s/4 hana",
    "hana",
    "abap",
    "fiori",
    # Módulos funcionales
    "sap erp",
    "sap ecc",
    "sap basis",
    "sap mm",
    "sap fi",
    "sap fi/co",
    "sap co",
    "sap sd",
    "sap hcm",
    "sap hr",
    "sap pi",
    "sap po",
    "sap pm",
    "sap ps",
    "sap qm",
    "sap wm",
    "sap ewm",
    "sap tm",
    "sap srm",
    "sap crm",
    "sap ssm",
    "sap bi",
    "sap bo",
    "sap bw",
    "sap bpc",
    "sap grc",
    "sap mdg",
    "sap mdm",
    "sap isu",
    "sap is-u",
    "sap re-fx",
    "sap refx",
    "sap re/fx",
    "sap apo",
    "sap scm",
    "sap ibp",
    "sap slm",
    "sap clm",
    "sap ariba",
    "sap fieldglass",
    "sap concur",
    "sap analytics cloud",
    "sac sap",
    # Suite cloud
    "successfactors",
    "ariba",
    "concur",
    "fieldglass",
    "sap cx",
    "sap customer experience",
    # Infraestructura / tecnología
    "netweaver",
    "bw/4hana",
    "bw4hana",
    "sap solution manager",
    "solman",
    "businessobjects",
    "business objects",
    "crystal reports",
    "sap oss",
    "sap early watch",
    "sap lumira",
    "sap build",
    "sap integration suite",
    "sap btp",
    "business technology platform",
    "sap cloud platform",
    # Términos genéricos asociados
    "implantación sap",
    "migración sap",
    "mantenimiento sap",
    "soporte sap",
    "consultoría sap",
    "formación sap",
    "licencias sap",
    "upgrade sap",
    "actualización sap",
]

# CPV codes relevantes (servicios TI / software)
CPV_PREFIXES_TI = [
    "72",  # Servicios TI
    "48",  # Paquetes de software
]

# URL base de la Plataforma de Contratación
PLACE_BASE_URL = "https://contrataciondelestado.es"
PLACE_SYNDICATION_BASE = f"{PLACE_BASE_URL}/sindicacion"

# Endpoint de búsqueda (form-based)
PLACE_SEARCH_URL = f"{PLACE_BASE_URL}/wps/portal/plataforma/buscadores/busqueda/"

# User agent identificable (buena práctica scraping ético)
USER_AGENT = "LicitacionesSAP-Bot/1.0"

# Feed ATOM en vivo — sindicación paginada de PLACE
PLACE_LIVE_ATOM_URL = (
    "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3.atom"
)

# Campos clave para detección de cambios (historial)
HISTORY_TRACKED_FIELDS = (
    "importe",
    "estado",
    "fecha_fin",
    "fecha_inicio",
    "duracion_valor",
    "duracion_unidad",
    "titulo",
    "descripcion",
)
