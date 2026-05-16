"""Cache backend abstracto para el dashboard.

Por defecto usa un diccionario en memoria. Si ``REDIS_URL`` está
configurado, usa Redis via redis-py (con ``StrictRedis``).

Uso:
    from dashboard.cache import get_cache
    cache = get_cache()
    cache.set("my_key", value, ttl=300)
    value = cache.get("my_key")  # None si expirado o no existe

La instancia es singleton por proceso (el inicializador se ejecuta una vez).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# ── Backends ─────────────────────────────────────────────────────────────────


class _MemoryBackend:
    """Cache en memoria con TTL. Thread-safe."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at)
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at != -1 and time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        expires_at = time.monotonic() + ttl if ttl > 0 else -1
        with self._lock:
            self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def keys(self, pattern: str = "*") -> list[str]:
        with self._lock:
            now = time.monotonic()
            return [
                k
                for k, (_, exp) in self._store.items()
                if exp == -1 or exp > now
            ]


class _RedisBackend:
    """Cache Redis. Serializa values como JSON."""

    def __init__(self, url: str) -> None:
        import redis  # type: ignore[import]

        self._r = redis.StrictRedis.from_url(url, decode_responses=True)
        log.info("cache.redis_connected", url=url.split("@")[-1])  # no logging password

    def get(self, key: str) -> Any | None:
        raw = self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        raw = json.dumps(value, ensure_ascii=False, default=str)
        if ttl > 0:
            self._r.setex(key, ttl, raw)
        else:
            self._r.set(key, raw)

    def delete(self, key: str) -> None:
        self._r.delete(key)

    def clear(self) -> None:
        self._r.flushdb()

    def keys(self, pattern: str = "*") -> list[str]:
        return list(self._r.keys(pattern))


# ── Singleton factory ─────────────────────────────────────────────────────────

_cache: _MemoryBackend | _RedisBackend | None = None
_cache_lock = threading.Lock()


def get_cache() -> _MemoryBackend | _RedisBackend:
    """Devuelve la instancia singleton del cache (inicializa al primer uso)."""
    global _cache
    if _cache is not None:
        return _cache
    with _cache_lock:
        if _cache is not None:
            return _cache
        from config import settings

        redis_url = getattr(settings, "REDIS_URL", "")
        if redis_url:
            try:
                _cache = _RedisBackend(redis_url)
                return _cache
            except Exception as exc:
                log.warning("cache.redis_init_failed", error=str(exc), fallback="memory")
        _cache = _MemoryBackend()
        log.info("cache.using_memory_backend")
        return _cache


def reset_cache() -> None:
    """Reinicia el singleton (útil en tests)."""
    global _cache
    with _cache_lock:
        _cache = None
