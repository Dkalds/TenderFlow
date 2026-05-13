"""Configuración global del proyecto — basada en pydantic-settings."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parent.parent

# En entornos donde el paquete se instala en site-packages (e.g. Streamlit Cloud),
# _ROOT apuntaría a un directorio sin permisos de escritura.  Usamos un
# directorio escribible como fallback.
_DEFAULT_DATA_DIR = _ROOT / "data"
if "site-packages" in str(_ROOT):
    _DEFAULT_DATA_DIR = Path("/tmp/licitaciones_data")  # noqa: S108


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
    DATA_DIR: Path = _DEFAULT_DATA_DIR
    DB_PATH: Path | None = None  # default calculado en validator
    DOWNLOADS_DIR: Path | None = None

    # ── Dashboard ────────────────────────────────────────────────────────
    DASHBOARD_PASSWORD: str = ""
    DASHBOARD_PASSWORD_HASH: str = ""  # bcrypt hash — requerido en ENV=prod
    DASHBOARD_CACHE_TTL: int = 300

    # ── ML ───────────────────────────────────────────────────────────────
    # Umbral de confianza para clasificar como SAP sin keywords (0.0–1.0)
    ML_CONFIDENCE_THRESHOLD: float = 0.70

    # ── Resiliencia ───────────────────────────────────────────────────────
    # Circuit breaker: backoff exponencial entre aperturas del circuito
    BREAKER_BASE_TIMEOUT: int = 60    # segundos — primer timeout tras apertura
    BREAKER_MAX_TIMEOUT: int = 1800   # segundos — techo del backoff (30 min)

    # ── OpenTelemetry ─────────────────────────────────────────────────────
    # Si está vacío, el tracing opera en modo NoOp (sin overhead)
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    OTEL_SERVICE_NAME: str = "licitaciones-sap"

    # ── OAuth ────────────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    OAUTH_REDIRECT_URI: str = "http://localhost:8501"
    OAUTH_ALLOWED_EMAILS: str = ""
    OAUTH_ALLOWED_DOMAINS: str = ""
    OAUTH_ADMIN_EMAILS: str = ""
    # Clave independiente para firmar tokens CSRF/OAuth state (HMAC-SHA256).
    # Si no se configura, se deriva de GOOGLE_CLIENT_SECRET como fallback.
    # En producción configura un valor aleatorio de 32+ caracteres:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    SIGNING_KEY: str = ""

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

    # ── Base de datos ─────────────────────────────────────────────────────
    DB_POOL_SIZE: int = 5
    DB_POOL_TIMEOUT: float = 10.0

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
        if self.ENV == "prod" and not self.DASHBOARD_PASSWORD_HASH:
            raise ValueError(
                "DASHBOARD_PASSWORD_HASH (hash bcrypt) es obligatorio en ENV=prod. "
                "Genera el hash con: python scripts/hash_password.py"
            )
        return self

    @field_validator("DASHBOARD_CACHE_TTL", mode="before")
    @classmethod
    def _parse_cache_ttl(cls, v: object) -> int:
        return int(v)  # type: ignore[call-overload, no-any-return]


def _load() -> Settings:
    return Settings()


_settings = _load()

# ── Singleton accesible para nuevos consumidores ─────────────────────────
# Uso recomendado: ``from config import settings`` y luego ``settings.DB_PATH``.
settings = _settings


def ensure_data_dirs() -> None:
    """Crea los directorios de datos si no existen."""
    _settings.DATA_DIR.mkdir(exist_ok=True)
    downloads = _settings.DOWNLOADS_DIR
    if downloads is not None:
        downloads.mkdir(exist_ok=True)
