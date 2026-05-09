"""Logging estructurado con structlog + correlation IDs por run.

Uso típico::

    from observability import configure_logging, get_logger, bind_run_context

    configure_logging(json_logs=True)
    log = get_logger(__name__)
    bind_run_context(run_id="abc123", module="scraper")
    log.info("month_start", year=2026, month=4)

Cuando ``json_logs=False`` (interactivo), imprime en color para lectura humana.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    merge_contextvars,
)

# ── Redacción de secretos ────────────────────────────────────────────────
_SENSITIVE_ENV_VARS = (
    "TURSO_AUTH_TOKEN",
    "DASHBOARD_PASSWORD",
    "ALERT_SMTP_PASSWORD",
    "GOOGLE_CLIENT_SECRET",
)

# Claves de event_dict cuyo valor SIEMPRE se redacta (independiente del contenido).
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "auth_token",
        "api_key",
        "apikey",
        "authorization",
        "cookie",
    }
)

_REDACTED = "***REDACTED***"


def _load_sensitive_values() -> set[str]:
    """Lee los valores actuales de las env vars sensibles. Vacíos se ignoran."""
    import os

    values: set[str] = set()
    for var in _SENSITIVE_ENV_VARS:
        v = os.environ.get(var, "")
        if v and len(v) >= 4:  # evita redactar strings triviales
            values.add(v)
    return values


def _redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Procesador structlog que redacta valores sensibles en cada evento.

    Aplica dos estrategias:
      1. Si la *clave* del campo coincide con un nombre sensible
         (password, token, secret, ...), se redacta el valor.
      2. Si el *valor* coincide con el contenido actual de una env var
         sensible (TURSO_AUTH_TOKEN, DASHBOARD_PASSWORD, etc.), se redacta.

    Es un best-effort defensivo: redacciones adicionales en el código que
    construye el log siguen siendo recomendables.
    """
    sensitive_values = _load_sensitive_values()

    for key, value in list(event_dict.items()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
            continue
        if isinstance(value, str) and value in sensitive_values:
            event_dict[key] = _REDACTED
        elif isinstance(value, str) and sensitive_values:
            # Sustituir cualquier ocurrencia incrustada (e.g. URLs con token)
            redacted = value
            for sv in sensitive_values:
                if sv in redacted:
                    redacted = redacted.replace(sv, _REDACTED)
            if redacted != value:
                event_dict[key] = redacted
    return event_dict


def _detect_json_default() -> bool:
    """Por defecto JSON en entornos no-TTY (CI, Docker, systemd)."""
    from config import settings

    fmt = settings.LOG_FORMAT.lower()
    if fmt == "json":
        return True
    if fmt == "console":
        return False
    return not sys.stderr.isatty()


def configure_logging(
    *,
    level: str | int = "INFO",
    json_logs: bool | None = None,
) -> None:
    """Configura structlog + logging stdlib para toda la app.

    Idempotente: llamar múltiples veces es seguro.
    """
    if json_logs is None:
        json_logs = _detect_json_default()

    shared_processors: list[structlog.types.Processor] = [
        merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_secrets,
    ]

    if json_logs:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Redirigir logs stdlib al formato estructurado
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    import typing

    return typing.cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))


def bind_run_context(**kwargs: Any) -> str:
    """Asocia un correlation_id y otros campos al contexto del thread.

    Si no se pasa ``run_id``, se genera uno nuevo (uuid4). Devuelve el run_id.
    """
    run_id = kwargs.pop("run_id", None) or uuid.uuid4().hex[:12]
    bind_contextvars(run_id=run_id, **kwargs)
    return run_id


def clear_run_context() -> None:
    clear_contextvars()


def bind_session_context() -> str | None:
    """Asocia el session_id de Streamlit al contexto de logging.

    Permite correlacionar logs del dashboard con la sesión del usuario.
    Devuelve el session_id (truncado) o None si no está en un contexto Streamlit.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        ctx = get_script_run_ctx()
        if ctx and ctx.session_id:
            import hashlib

            session_hash = hashlib.sha256(ctx.session_id.encode()).hexdigest()[:12]
            bind_contextvars(session_id=session_hash)
            return session_hash
    except Exception:
        structlog.get_logger(__name__).debug("streamlit_session_bind_failed")
    return None
