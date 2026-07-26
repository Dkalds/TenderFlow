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
import re
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
    "DATABASE_URL",  # DSN Postgres/Supabase con user:pass embebidos (ADR-016)
    "DASHBOARD_PASSWORD",
    "DASHBOARD_PASSWORD_HASH",
    "ALERT_SMTP_PASSWORD",
    "GOOGLE_CLIENT_SECRET",
    "API_HMAC_SECRET",
    "SIGNING_KEY",
    "REDIS_PASSWORD",
    "GF_SECURITY_ADMIN_PASSWORD",
)

# Password embebida en un DSN Postgres/Supabase (el tramo entre el ':' del usuario
# y el '@' del host). Se redacta aunque el DSN no coincida con el valor cacheado en
# env (p.ej. reformateado por psycopg/SQLAlchemy dentro de un mensaje de error).
_DSN_PASSWORD_RE = re.compile(r"(postgres(?:ql)?://[^:/?#@\s]+:)[^@/?#\s]+(@)")


def redact_dsn(text: str) -> str:
    """Redacta la password embebida en DSNs Postgres/Supabase.

    Reemplaza por ``***`` la password (el tramo entre el ':' del usuario y el '@'
    del host). Conserva user/host/db (no secretos) para preservar utilidad de
    debug. Seguro sobre texto sin DSN (no-op).
    """
    return _DSN_PASSWORD_RE.sub(r"\1***\2", text)


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

# Authentication and operational logs are broadly accessible during an
# incident. They must not become a secondary database of personal data.
_PERSONAL_KEYS = frozenset({"email", "recipient", "recipients"})
_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
_URL_QUERY_SECRET_RE = re.compile(
    r"([?&](?:access_)?(?:token|api[_-]?key|secret|signature|sig|password|auth)=)[^&#\s]+",
    re.IGNORECASE,
)

_REDACTED = "***REDACTED***"

# Cache de valores sensibles — se actualiza una única vez en configure_logging().
# Evita leer os.environ en cada evento de log.
_cached_sensitive_values: set[str] = set()

# Flag de idempotencia — True si configure_logging() ya ha sido invocado.
_configured: bool = False


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

    Usa el cache de valores sensibles calculado en configure_logging() para
    evitar llamadas repetidas a os.environ en cada evento de log.
    """
    sensitive_values = _cached_sensitive_values

    for key, value in list(event_dict.items()):
        if key.lower() in _SENSITIVE_KEYS:
            event_dict[key] = _REDACTED
            continue
        if key.lower() in _PERSONAL_KEYS:
            event_dict[key] = _REDACTED
            continue
        if not isinstance(value, str):
            continue
        if value in sensitive_values:
            event_dict[key] = _REDACTED
            continue
        # Sustituir cualquier ocurrencia incrustada de un valor sensible (e.g. URLs con token)
        redacted = value
        for sv in sensitive_values:
            if sv in redacted:
                redacted = redacted.replace(sv, _REDACTED)
        # Redacta passwords en DSNs Postgres aunque no coincidan con un valor cacheado.
        redacted = redact_dsn(redacted)
        # Errores de proveedores y URLs de callback pueden incluir tanto emails
        # como tokens en query string; el log conserva el contexto no sensible.
        redacted = _EMAIL_RE.sub("<email-redacted>", redacted)
        redacted = _URL_QUERY_SECRET_RE.sub(r"\1" + _REDACTED, redacted)
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
    Actualiza el cache de valores sensibles para el processor de redacción.
    """
    global _cached_sensitive_values
    _cached_sensitive_values = _load_sensitive_values()
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

    global _configured
    _configured = True


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
    """No-op — session context binding has been removed."""
    return None
