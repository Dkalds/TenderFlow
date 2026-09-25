"""Interfaz unificada de rate limiting.

Centraliza la elección de backend (base de datos o Redis) mediante una
factory. Las implementaciones concretas delegan en los módulos existentes:

* :class:`DbRateLimiter`     — ventana deslizante en la tabla ``rate_limits``.
* :class:`RedisRateLimiter`  — sorted set en Redis, con la BD de respaldo.

Uso::

    from services.rate_limiting import get_rate_limiter

    limiter = get_rate_limiter()
    allowed = limiter.check("ak:abc123", max_calls=120, window_seconds=60)

**Elección de backend** — variable de entorno ``RATE_LIMIT_BACKEND``:

* ``auto`` (**por defecto** desde 2026-09): Redis si hay ``REDIS_URL`` (y el
  paquete ``redis``); si no, la BD. Que Redis sea *alcanzable* se decide en cada
  comprobación, no al arrancar: si no responde, esa comprobación la resuelve la
  BD y Redis queda en enfriamiento (``services.rate_limit_redis.ENFRIAMIENTO_S``)
  sin reintentar la conexión en cada petición. Así ni un Redis caído durante el
  arranque condena el proceso a la BD para siempre, ni uno que cae después deja
  la API sin límite. Hasta 2026-09 el default era ``db`` aunque producción
  tuviera ``REDIS_URL``: cada petición hacía ~5 viajes a Postgres solo para
  contarse.
* ``redis``: lo mismo que ``auto``, pero avisa en el log si falta ``REDIS_URL``,
  porque se pidió explícitamente y no se puede cumplir.
* ``db``: siempre la tabla ``rate_limits``, aunque haya Redis. Es el
  interruptor para volver al comportamiento anterior sin desplegar. ``sqlite``
  se sigue aceptando como alias histórico: el motor es Postgres desde ADR-021,
  pero el valor pudo quedar fijado en despliegues anteriores.

Un valor desconocido se trata como ``auto`` y se avisa en el log.

**Ante fallos nunca se abre el límite:**

* Error de BD → se deniega (fail-closed, ``db.rate_limits.check_rate_limit_db``).
* Error de Redis → esa comprobación cae a la BD (y, si la BD también falla, se
  deniega). Los contadores de Redis y de la BD no se coordinan, así que en la
  transición un cliente puede estrenar cuota en el otro almacén: es el precio de
  degradar sin quedarse sin límite.

**Bloqueo.** ``check()`` es síncrono y hace E/S de red: un viaje a Redis o
varios a Postgres. Desde código ``async`` hay que despacharlo a un hilo; el
``RateLimitMiddleware`` lo hace con su propio ``CapacityLimiter`` y el resto de
consumidores async (``api/routes/security.py``, ``api/routes/auth.py``) con
``run_db``.
"""

from __future__ import annotations

import os
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

#: Valores de ``RATE_LIMIT_BACKEND`` que fuerzan la base de datos.
_BACKENDS_BD = frozenset({"db", "sqlite"})
_BACKENDS_VALIDOS = _BACKENDS_BD | {"auto", "redis"}

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
    backend = os.getenv("RATE_LIMIT_BACKEND", "auto").strip().lower()
    if backend not in _BACKENDS_VALIDOS:
        log.warning("rate_limiting_backend_desconocido", valor=backend, usando="auto")
        backend = "auto"

    if backend in _BACKENDS_BD:
        log.info("rate_limiting_backend_db", modo=backend)
        return DbRateLimiter()

    from services.rate_limit_redis import has_redis

    if has_redis():
        log.info("rate_limiting_backend_redis", modo=backend)
        return RedisRateLimiter()
    if backend == "redis":
        log.warning("rate_limiting_redis_requested_but_unavailable_using_db")
    log.info("rate_limiting_backend_db", modo=backend)
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
