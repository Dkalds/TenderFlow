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


# Palabras clave para filtrar licitaciones SAP (mantenido por retrocompatibilidad)
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

# ── Keywords por tecnología (multi-vendor) ───────────────────────────────
# Diccionario {tecnología: [keywords]}. El scraper filtra licitaciones que
# coincidan con al menos una tecnología.
TECHNOLOGY_KEYWORDS: dict[str, list[str]] = {
    "SAP": SAP_KEYWORDS,
    "SALESFORCE": [
        "salesforce",
        "sales cloud",
        "service cloud",
        "marketing cloud",
        "commerce cloud",
        "experience cloud",
        "community cloud",
        "salesforce cpq",
        "salesforce crm",
        "pardot",
        "mulesoft",
        "tableau crm",
        "einstein analytics",
        "salesforce einstein",
        "heroku",
        "apex salesforce",
        "visualforce",
        "lightning",
        "salesforce platform",
        "force.com",
        "data cloud salesforce",
        "implantación salesforce",
        "migración salesforce",
        "mantenimiento salesforce",
        "soporte salesforce",
        "consultoría salesforce",
        "licencias salesforce",
    ],
    "ORACLE": [
        "oracle",
        "oracle erp",
        "oracle cloud",
        "oracle fusion",
        "oracle ebs",
        "e-business suite",
        "oracle hcm",
        "oracle financials",
        "peoplesoft",
        "jd edwards",
        "oracle database",
        "oracle db",
        "oracle weblogic",
        "oracle forms",
        "oracle apex",
        "oracle bi",
        "oracle analytics",
        "oracle integration cloud",
        "oracle soa",
        "primavera oracle",
        "siebel",
        "oracle netsuite",
        "netsuite",
        "pl/sql",
        "plsql",
        "implantación oracle",
        "migración oracle",
        "mantenimiento oracle",
        "soporte oracle",
        "consultoría oracle",
        "licencias oracle",
    ],
    "MICROSOFT": [
        "microsoft dynamics",
        "dynamics 365",
        "dynamics crm",
        "dynamics nav",
        "dynamics ax",
        "dynamics bc",
        "business central",
        "navision",
        "axapta",
        "power platform",
        "power bi",
        "power apps",
        "power automate",
        "microsoft azure",
        "azure devops",
        "sharepoint",
        "microsoft 365",
        "office 365",
        "microsoft teams",
        "sql server",
        "azure sql",
        ".net",
        "dotnet",
        "implantación dynamics",
        "migración dynamics",
        "mantenimiento dynamics",
        "soporte dynamics",
        "consultoría dynamics",
        "licencias dynamics",
        "licencias microsoft",
    ],
    "SERVICENOW": [
        "servicenow",
        "service now",
        "servicenow itsm",
        "servicenow itom",
        "servicenow hrsd",
        "servicenow csm",
        "implantación servicenow",
        "soporte servicenow",
        "licencias servicenow",
    ],
    "WORKDAY": [
        "workday",
        "workday hcm",
        "workday financials",
        "workday adaptive",
        "workday prism",
        "implantación workday",
        "soporte workday",
        "licencias workday",
    ],
    "IBM": [
        "ibm maximo",
        "ibm cognos",
        "ibm websphere",
        "ibm db2",
        "ibm cloud",
        "ibm watson",
        "ibm filenet",
        "ibm bpm",
        "lotus notes",
        "ibm as/400",
        "ibm iseries",
        "rpg ibm",
    ],
    "OPENTEXT": [
        "opentext",
        "open text",
        "documentum",
        "content server",
        "opentext ecm",
        "opentext extended ecm",
    ],
    "UNIT4": [
        "unit4",
        "unit 4",
        "unit4 erp",
        "unit4 financials",
        "agresso",
    ],
    "META4": [
        "meta4",
        "meta 4",
        "meta4 peoplenet",
        "peoplenet",
        "cezanne hr",
    ],
    "SOPRA": [
        "sopra",
        "sopra steria",
        "sap sopra",
    ],
    "SAGE": [
        "sage erp",
        "sage x3",
        "sage 200",
        "sage despachos",
        "sage murano",
        "sage 50",
    ],
    "INFOR": [
        "infor erp",
        "infor ln",
        "infor m3",
        "infor cloudsuite",
        "infor os",
        "baan",
    ],
}

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
