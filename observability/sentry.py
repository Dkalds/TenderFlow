"""Integración opcional de Sentry (F5).

Es **opt-in** vía la variable ``SENTRY_DSN``. Si no está configurada, el
módulo opera en modo no-op sin overhead ni dependencias.

Captura contexto adicional cuando hay un usuario OAuth autenticado
(``user.id`` opaco, nunca PII directa).

Uso típico (entrypoints)::

    from observability.sentry import configure_sentry
    configure_sentry(service="licitaciones-api")
"""

from __future__ import annotations

import os
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_configured = False


def configure_sentry(*, service: str = "licitaciones", traces_sample_rate: float = 0.05) -> bool:
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
        import sentry_sdk  # type: ignore[import-not-found]
        from sentry_sdk.integrations.logging import (  # type: ignore[import-not-found]
            LoggingIntegration,
        )
    except ImportError:
        log.warning("sentry_sdk_missing", hint="pip install sentry-sdk")
        _configured = True
        return False

    environment = os.getenv("ENVIRONMENT", "dev")
    release = os.getenv("APP_VERSION") or os.getenv("GIT_SHA")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=traces_sample_rate,
        send_default_pii=False,
        integrations=[LoggingIntegration(level=None, event_level=None)],
        before_send=_strip_pii,
    )
    sentry_sdk.set_tag("service", service)
    log.info("sentry_configured", service=service, env=environment, sample=traces_sample_rate)
    _configured = True
    return True


_PII_KEYS = {"email", "password", "api_key", "token", "authorization", "cookie"}


def _strip_pii(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Limpia campos sensibles antes de enviar al backend."""
    headers = event.get("request", {}).get("headers", {})
    for k in list(headers):
        if k.lower() in _PII_KEYS:
            headers[k] = "***REDACTED***"
    user = event.get("user") or {}
    user.pop("email", None)
    user.pop("ip_address", None)
    if user:
        event["user"] = user
    return event


def set_user_context(user_id_hash: str, *, locale: str | None = None) -> None:
    """Asocia el span/scope actual a un usuario opaco (hash)."""
    try:
        import sentry_sdk
    except ImportError:
        return
    sentry_sdk.set_user({"id": user_id_hash, **({"locale": locale} if locale else {})})


__all__ = ["configure_sentry", "set_user_context"]
