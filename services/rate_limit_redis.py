"""Backend Redis opcional para rate limiting (F4, extra ``[scale]``).

Mantiene API compatible con ``db.rate_limits.check_rate_limit_db`` para
permitir cambiar de backend con una variable de entorno
(``RATE_LIMIT_BACKEND=redis``). Si Redis no está disponible o no se
configura, cae al backend SQLite existente.

Diseño:

* Ventana deslizante en un sorted set por clave: ``ZADD`` con timestamp,
  ``ZREMRANGEBYSCORE`` para purgar fuera de ventana, ``ZCARD`` para contar.
* TTL sobre la clave igual a la ventana, para evitar fugas en claves
  abandonadas.
* Operaciones combinadas en una pipeline para minimizar RTTs.

Instalación opcional: ``pip install licitaciones-sap[scale]``
(la dependencia ``redis`` se declara en pyproject como extra).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

try:  # pragma: no cover - dependencia opcional
    import redis

    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    redis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False


_lock = threading.Lock()
_client: Any = None


def has_redis() -> bool:
    return _REDIS_AVAILABLE and bool(os.getenv("REDIS_URL"))


def _get_client() -> Any | None:
    global _client
    if not has_redis():
        return None
    with _lock:
        if _client is None:
            url = os.getenv("REDIS_URL", "")
            try:
                _client = redis.Redis.from_url(
                    url,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                    decode_responses=False,
                )
                _client.ping()
                log.info("ratelimit_redis_connected", url_host=url.split("@")[-1])
            except Exception as exc:
                log.warning("ratelimit_redis_unavailable", error=str(exc))
                _client = None
        return _client


def check_rate_limit_redis(
    key: str,
    *,
    max_calls: int = 120,
    window_seconds: float = 60.0,
) -> bool | None:
    """Versión Redis de :func:`db.rate_limits.check_rate_limit_db`.

    Devuelve:
        * ``True`` si el request está permitido.
        * ``False`` si excede el límite.
        * ``None`` si Redis no está disponible (caller debe usar fallback).
    """
    client = _get_client()
    if client is None:
        return None

    now = time.time()
    window_start = now - window_seconds
    member = f"{now:.6f}:{os.getpid()}"

    try:
        pipe = client.pipeline()
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, int(window_seconds) + 1)
        _, _, count, _ = pipe.execute()
    except Exception as exc:
        log.warning("ratelimit_redis_op_failed", error=str(exc))
        return None

    allowed = int(count) <= max_calls
    if not allowed:
        log.info("ratelimit_redis_exceeded", key=key, count=int(count), limit=max_calls)
    return allowed


def check_rate_limit(
    key: str,
    *,
    max_calls: int = 120,
    window_seconds: float = 60.0,
) -> bool:
    """Dispatcher: Redis si configurado y operativo; SQLite como fallback.

    Permite cambiar de backend con ``RATE_LIMIT_BACKEND=redis|sqlite``.
    """
    backend = os.getenv("RATE_LIMIT_BACKEND", "sqlite").lower()
    if backend == "redis":
        result = check_rate_limit_redis(key, max_calls=max_calls, window_seconds=window_seconds)
        if result is not None:
            return result
        log.debug("ratelimit_redis_fallback_to_sqlite", key=key)

    from db.rate_limits import check_rate_limit_db

    return check_rate_limit_db(key, max_calls=max_calls, window_seconds=window_seconds)


__all__ = ["check_rate_limit", "check_rate_limit_redis", "has_redis"]
