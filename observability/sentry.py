"""Integración opcional de Sentry (F5).

Es **opt-in** vía la variable ``SENTRY_DSN``. Si no está configurada, el
módulo opera en modo no-op sin overhead.

``sentry-sdk`` viaja en los lockfiles desde 2026-10-11. Hasta entonces este
módulo y la variable existían, pero el paquete no estaba en ningún
``requirements*``: con el DSN puesto, la API registraba ``sentry_sdk_missing``
y seguía sin capturar nada.

**Qué no sale de aquí**, y es la misma regla que sigue el frontend
(``web/src/lib/sentry-opciones.ts``):

- La query string, las cookies y el cuerpo de la petición.
- De las cabeceras, todas menos tres (``host``, ``user-agent`` y ``referer``).
  Es una lista de las que pasan y no de las que se quitan: la clave de API
  viaja en ``X-API-Key`` y la IP del visitante en ``X-Forwarded-For``, y una
  lista de vetadas se queda corta el día que alguien añade una cabecera.
- Del usuario, todo menos un ``id`` opaco.
- Las variables locales de cada marco de la pila: ahí están los parámetros de
  las consultas, los DTO de la petición y las filas leídas.
- Las migas que no sean de salida HTTP, y de esas la query. Las de Redis
  llevan la clave, que en el rate limiting es la IP del cliente.

Solo errores: sin trazas de rendimiento por defecto (sus spans llevan la URL
completa de cada llamada saliente), igual que el frontend.

Uso típico (entrypoints)::

    from observability.sentry import configure_sentry
    configure_sentry(service="licitaciones-api")
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from observability.logging import get_logger

if TYPE_CHECKING:  # solo para anotar; el SDK se importa al configurar
    from sentry_sdk.types import Breadcrumb, BreadcrumbHint, Event, Hint

log = get_logger(__name__)

_configured = False

_CABECERAS_PERMITIDAS = frozenset({"host", "user-agent", "referer"})
_QUERY_RE = re.compile(r"[?#].*$")

#: Códigos de respuesta que cuentan como error del servidor. El 503 queda
#: fuera: en esta API es una degradación declarada (`/explain` sin
#: scikit-learn, el índice de búsqueda sin construir), se lanza a propósito y
#: en cada petición. Lo inesperado llega como excepción, y esa se captura.
_CODIGOS_DE_ERROR = frozenset(range(500, 600)) - {503}


def _sin_query(url: str) -> str:
    """La URL sin query ni fragmento."""
    return _QUERY_RE.sub("", url)


def _entorno() -> str:
    # `ENV` es la variable que declara `render.yaml` y valida
    # `config/settings.py`; `ENVIRONMENT` se conserva por compatibilidad.
    return os.getenv("ENVIRONMENT") or os.getenv("ENV") or "dev"


def _version() -> str | None:
    # Render pone `RENDER_GIT_COMMIT` en cada servicio y Actions `GITHUB_SHA`.
    for nombre in ("APP_VERSION", "GIT_SHA", "RENDER_GIT_COMMIT", "GITHUB_SHA"):
        valor = os.getenv(nombre, "").strip()
        if valor:
            return valor
    return None


def configure_sentry(*, service: str = "licitaciones", traces_sample_rate: float = 0.0) -> bool:
    """Inicializa Sentry si ``SENTRY_DSN`` está definido y el SDK está instalado.

    Devuelve True si quedó activo, False en otro caso.
    """
    global _configured
    if _configured:
        return True

    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        log.debug("sentry_disabled", reason="SENTRY_DSN no configurado")
        _configured = True
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError:
        # Instalación sin los lockfiles del proyecto (`pip install` suelto).
        log.warning("sentry_sdk_missing", hint="pip install sentry-sdk")
        _configured = True
        return False

    environment = _entorno()

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=_version(),
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        integrations=[
            LoggingIntegration(level=None, event_level=None),
            StarletteIntegration(failed_request_status_codes=set(_CODIGOS_DE_ERROR)),
            FastApiIntegration(failed_request_status_codes=set(_CODIGOS_DE_ERROR)),
        ],
        before_send=_strip_pii,
        before_send_transaction=_strip_pii,
        before_breadcrumb=_limpiar_miga,
    )
    sentry_sdk.set_tag("service", service)
    # La API y el worker arrancan el mismo `api.app:app`; lo que los distingue
    # es el perfil (`render.yaml`).
    perfil = os.getenv("APP_PROFILE", "").strip()
    if perfil:
        sentry_sdk.set_tag("app_profile", perfil)
    log.info("sentry_configured", service=service, env=environment, sample=traces_sample_rate)
    _configured = True
    return True


def _strip_pii(event: Event, _hint: Hint) -> Event:
    """Recorta el evento a lo que este módulo declara que envía."""
    request = event.get("request")
    if request:
        url = request.get("url")
        if isinstance(url, str):
            request["url"] = _sin_query(url)
        for campo in ("query_string", "cookies", "data", "env"):
            request.pop(campo, None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for nombre in list(headers):
                clave = str(nombre).lower()
                valor = headers[nombre]
                if clave not in _CABECERAS_PERMITIDAS:
                    del headers[nombre]
                elif clave == "referer" and isinstance(valor, str):
                    headers[nombre] = _sin_query(valor)
    user = event.get("user")
    if user is not None:
        event["user"] = {"id": user["id"]} if user.get("id") is not None else {}
    return event


def _limpiar_miga(miga: Breadcrumb, _hint: BreadcrumbHint) -> Breadcrumb | None:
    """Deja pasar solo las migas de salida HTTP, sin su query."""
    if miga.get("type") != "http":
        return None
    data = miga.get("data")
    if isinstance(data, dict):
        url = data.get("url")
        if isinstance(url, str):
            data["url"] = _sin_query(url)
        for campo in ("http.query", "http.fragment"):
            data.pop(campo, None)
    return miga


def set_user_context(user_id_hash: str, *, locale: str | None = None) -> None:
    """Asocia el span/scope actual a un usuario opaco (hash)."""
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.set_user({"id": user_id_hash, **({"locale": locale} if locale else {})})


__all__ = ["configure_sentry", "set_user_context"]
