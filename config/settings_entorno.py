"""Ejes del proceso: qué datos toca (``ENV``), qué arranca (``APP_PROFILE``) y dónde escribe.

Base de los mixins de ``config/settings.py`` cuyos validadores dependen del
entorno o del perfil (P3 «Los dos módulos-dios»): las propiedades de gating
(``_is_prod_data``, ``_serves_http``…) viven aquí para que cada dominio decida
con la misma regla. ``Settings`` hereda de todos, así que los nombres de las
variables de entorno y el acceso (``settings.ENV``) son los de siempre.

Sin ``model_config`` propio, por lo mismo que ``config/settings_resumen.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import model_validator
from pydantic_settings import BaseSettings

_ROOT = Path(__file__).resolve().parent.parent


# En entornos donde el paquete se instala en site-packages (e.g. despliegues gestionados),
# _ROOT apuntaría a un directorio sin permisos de escritura.  Usamos un
# directorio escribible como fallback.
_DEFAULT_DATA_DIR = _ROOT / "data"
if "site-packages" in str(_ROOT):
    _DEFAULT_DATA_DIR = Path("/tmp/licitaciones_data")  # noqa: S108


class EntornoSettings(BaseSettings):
    """Entorno, perfil, rutas de datos y las propiedades de gating de los validadores."""

    # ── Entorno ──────────────────────────────────────────────────────────
    # ENV describe **qué datos** toca el proceso (dev/staging/prod).
    # APP_PROFILE describe **qué componentes** arranca. Son ejes ortogonales:
    # el scraper del cron toca datos de producción (ENV=prod) pero no sirve
    # HTTP, así que no necesita SIGNING_KEY ni REDIS_URL. Antes ambos ejes
    # viajaban en ENV, lo que obligaba al cron a declarar ENV=dev contra la BD
    # de producción y desactivaba de paso validators que sí le aplicaban
    # (ver el fix de sslmode en _validate_prod_database_ssl).
    ENV: Literal["dev", "staging", "prod"] = "prod"
    # `mcp` es el servidor MCP interno (`python -m mcp_server`): no sirve la API
    # REST ni es un worker, pero sí firma tokens y audita, así que exige
    # `SIGNING_KEY` y `AUDIT_HMAC_KEY` como la API y nada de lo demás (CORS,
    # API keys, webhooks...). Tampoco relaja el techo de tiempo por consulta.
    APP_PROFILE: Literal["api", "worker", "scraper", "mcp"] = "api"

    # ── Rutas ────────────────────────────────────────────────────────────
    DATA_DIR: Path = _DEFAULT_DATA_DIR
    DOWNLOADS_DIR: Path | None = None

    @model_validator(mode="after")
    def _set_derived_paths(self) -> Self:
        if self.DOWNLOADS_DIR is None:
            self.DOWNLOADS_DIR = self.DATA_DIR / "downloads"
        return self

    # ── Helpers de gating de validators ──────────────────────────────────
    # Regla: los validators se agrupan por *lo que el proceso hace*, no por
    # el entorno. `_serves_http` marca los secretos que solo tienen sentido
    # cuando el proceso expone la API (CSRF, API keys, CORS, caché Redis).
    # Los validators de BD, alertas y contraseñas aplican a todos los perfiles.

    @property
    def _is_prod_data(self) -> bool:
        """True si el proceso toca datos de producción o staging."""
        return self.ENV in ("prod", "staging")

    @property
    def _serves_http(self) -> bool:
        """True si el proceso expone la API HTTP (perfil ``api``)."""
        return self.APP_PROFILE == "api"

    @property
    def _es_mcp(self) -> bool:
        """True si el proceso es el servidor MCP interno (perfil ``mcp``)."""
        return self.APP_PROFILE == "mcp"

    @property
    def _firma_y_audita(self) -> bool:
        """True si el proceso firma tokens y escribe en ``audit_log`` (``api`` y ``mcp``)."""
        return self._serves_http or self._es_mcp
