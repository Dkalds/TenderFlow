"""Interfaz unificada de rate limiting.

Centraliza la elección de backend (base de datos o Redis) mediante una
factory. Las implementaciones concretas delegan en los módulos existentes:

* :class:`DbRateLimiter`     — ventana deslizante en la tabla ``rate_limits``.
* :class:`RedisRateLimiter`  — sorted set en Redis (requiere extra ``[scale]``).

Uso::

    from services.rate_limiting import get_rate_limiter

    limiter = get_rate_limiter()
    allowed = limiter.check("ak:abc123", max_calls=120, window_seconds=60)

El backend se selecciona mediante la variable de entorno
``RATE_LIMIT_BACKEND`` (``redis`` | ``db``, por defecto ``db``) o según
disponibilidad de Redis si está configurado. ``sqlite`` se sigue aceptando
como alias histórico de ``db``: el motor es Postgres desde ADR-021, pero el
valor pudo quedar fijado en despliegues anteriores.
"""

from __future__ import annotations

from typing import Protocol

from observability.logging import get_logger

log = get_logger(__name__)


# ── Protocolo ────────────────────────────────────────────────────────────────


class RateLimiter(Protocol):
    """Interfaz mínima que todo backend de rate limiting debe cumplir."""

    def check(
        self,
        key: str,
        *,
        max_calls: int = 120,
        window_seconds: float = 60.0,
    ) -> bool:
        """Devuelve ``True`` si el request está dentro del límite; ``False`` si lo excede."""
        ...


# ── Implementaciones ─────────────────────────────────────────────────────────


class DbRateLimiter:
    """Backend de base de datos — ventana deslizante en ``rate_limits``."""

    def check(
        self,
        key: str,
        *,
        max_calls: int = 120,
        window_seconds: float = 60.0,
    ) -> bool:
        from db.rate_limits import check_rate_limit_db

        return check_rate_limit_db(key, max_calls=max_calls, window_seconds=window_seconds)


class RedisRateLimiter:
    """Backend Redis — ventana deslizante en sorted set.

    Cae automáticamente al backend de BD si Redis no está disponible.
    """

    def check(
        self,
        key: str,
        *,
        max_calls: int = 120,
        window_seconds: float = 60.0,
    ) -> bool:
        from services.rate_limit_redis import check_rate_limit_redis

        result = check_rate_limit_redis(key, max_calls=max_calls, window_seconds=window_seconds)
        if result is not None:
            return result
        # Redis no disponible — fallback al backend de BD
        log.debug("rate_limiting_redis_fallback_db", key=key)
        return DbRateLimiter().check(key, max_calls=max_calls, window_seconds=window_seconds)


# ── Factory ──────────────────────────────────────────────────────────────────

_instance: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """Devuelve el limiter singleton según ``RATE_LIMIT_BACKEND`` / disponibilidad.

    El singleton se inicializa en el primer acceso. Para forzar re-inicialización
    (útil en tests), llamar a :func:`reset_rate_limiter`.
    """
    global _instance
    if _instance is None:
        _instance = _create_limiter()
    return _instance


def reset_rate_limiter() -> None:
    """Descarta el singleton (útil en tests para cambiar el backend)."""
    global _instance
    _instance = None


def _create_limiter() -> RateLimiter:
    import os

    backend = os.getenv("RATE_LIMIT_BACKEND", "db").lower()
    if backend == "redis":
        from services.rate_limit_redis import has_redis

        if has_redis():
            log.info("rate_limiting_backend_redis")
            return RedisRateLimiter()
        log.warning("rate_limiting_redis_requested_but_unavailable_using_db")

    log.info("rate_limiting_backend_db")
    return DbRateLimiter()


# Alias histórico: el motor es Postgres desde ADR-021, pero el nombre viejo
# pudo quedar importado en código externo o en configuración.
SqliteRateLimiter = DbRateLimiter

__all__ = [
    "DbRateLimiter",
    "RateLimiter",
    "RedisRateLimiter",
    "SqliteRateLimiter",
    "get_rate_limiter",
    "reset_rate_limiter",
]
