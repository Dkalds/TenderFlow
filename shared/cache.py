"""Cache unificado con backends Memory (LRU+TTL) y Redis.

Reemplaza las implementaciones históricas de caché con una única implementación
thread-safe y correctamente testeada.

Uso::

    from shared.cache import get_cache

    cache = get_cache("api")          # namespace "api", backend auto-detectado
    cache.set("key", value, ttl=60)
    value = cache.get("key")
    cache.delete("key")

Backends:
  - **Memory** (default): ``OrderedDict`` con LRU eviction y TTL por entrada.
    Thread-safe con ``threading.Lock``.
  - **Redis** (si ``REDIS_URL`` está configurado): Compartido entre procesos/workers.
    Falla de forma silenciosa volviendo a Memory si Redis no está disponible.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel

from observability.logging import get_logger

log = get_logger(__name__)

_MEMORY_MAX_SIZE = 256  # entradas máximas por namespace en modo memory


# ---------------------------------------------------------------------------
# Backend abstracto (duck-typed Protocol)
# ---------------------------------------------------------------------------


class _MemoryBackend:
    """Cache en memoria con LRU eviction y TTL. Thread-safe."""

    def __init__(self, max_size: int = _MEMORY_MAX_SIZE) -> None:
        self._store: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at != -1 and time.monotonic() > expires_at:
                self._store.pop(key, None)
                return None
            # LRU: mover al final (most recently used)
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: float = 60.0) -> None:
        with self._lock:
            expires_at = -1 if ttl <= 0 else time.monotonic() + ttl
            if key in self._store:
                self._store[key] = (value, expires_at)
                self._store.move_to_end(key)
                return
            # Evicción: primero los expirados
            if len(self._store) >= self._max_size:
                now = time.monotonic()
                expired = [k for k, (_, exp) in self._store.items() if exp != -1 and exp < now]
                for k in expired:
                    self._store.pop(k, None)
            # Luego LRU si aún hace falta
            while len(self._store) >= self._max_size:
                self._store.popitem(last=False)
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
            all_keys = [k for k, (_, exp) in self._store.items() if exp == -1 or exp > now]
        if pattern == "*":
            return all_keys
        # Simple glob: solo soportamos "prefix*"
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return [k for k in all_keys if k.startswith(prefix)]
        return [k for k in all_keys if k == pattern]

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


class _RedisBackend:
    """Cache Redis con serialización JSON. Falla en silencio a Memory."""

    def __init__(self, url: str, namespace: str = "") -> None:
        import redis as redis_lib

        self._ns = f"{namespace}:" if namespace else ""
        self._r: Any = redis_lib.Redis.from_url(
            url, decode_responses=True, socket_connect_timeout=2
        )
        self._r.ping()

    def _k(self, key: str) -> str:
        return f"{self._ns}{key}"

    def get(self, key: str) -> Any | None:
        try:
            raw = self._r.get(self._k(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            log.debug("shared_cache_redis_get_error", key=key, error=str(exc))
            return None

    def set(self, key: str, value: Any, ttl: float = 60.0) -> None:
        try:
            serialized = json.dumps(value, ensure_ascii=False, default=str)
            if ttl > 0:
                self._r.setex(self._k(key), int(ttl), serialized)
            else:
                self._r.set(self._k(key), serialized)
        except Exception as exc:
            log.debug("shared_cache_redis_set_error", key=key, error=str(exc))

    def delete(self, key: str) -> None:
        try:
            self._r.delete(self._k(key))
        except Exception:
            pass

    def clear(self) -> None:
        """Elimina solo las keys con el namespace actual (no flushdb)."""
        try:
            pattern = f"{self._ns}*" if self._ns else "*"
            cursor = 0
            while True:
                cursor, keys = self._r.scan(cursor=cursor, match=pattern, count=100)
                if keys:
                    self._r.delete(*keys)
                if cursor == 0:
                    break
        except Exception as exc:
            log.debug("shared_cache_redis_clear_error", error=str(exc))

    def keys(self, pattern: str = "*") -> list[str]:
        try:
            full_pattern = f"{self._ns}{pattern}"
            result: list[str] = []
            cursor = 0
            ns_len = len(self._ns)
            while True:
                cursor, keys = self._r.scan(cursor=cursor, match=full_pattern, count=100)
                result.extend(k[ns_len:] for k in keys)
                if cursor == 0:
                    break
            return result
        except Exception as exc:
            log.debug("shared_cache_redis_keys_error", error=str(exc))
            return []


# ---------------------------------------------------------------------------
# Singleton factory por namespace
# ---------------------------------------------------------------------------

_instances: dict[str, _MemoryBackend | _RedisBackend] = {}
_instances_lock = threading.Lock()
_redis_available: bool | None = None


def get_cache(namespace: str = "default") -> _MemoryBackend | _RedisBackend:
    """Devuelve el backend de cache para ``namespace``.

    Singleton por namespace: primera llamada crea la instancia (Redis si
    ``REDIS_URL`` está configurado, Memory como fallback).

    Args:
        namespace: Identificador lógico del cache (ej. "api", "analytics").
                   Prefija todas las keys en Redis para evitar colisiones.
    """
    if namespace in _instances:
        return _instances[namespace]

    with _instances_lock:
        # Double-checked locking
        if namespace in _instances:
            return _instances[namespace]

        backend: _MemoryBackend | _RedisBackend = _try_redis(namespace)
        _instances[namespace] = backend
        return backend


def _try_redis(namespace: str) -> _MemoryBackend | _RedisBackend:
    """Intenta conectar con Redis; si falla devuelve MemoryBackend.

    Siempre falla suavemente a MemoryBackend — es preferible tener datos
    potencialmente stale a devolver 500.  El error se loggea a nivel
    ``error`` para que monitoreo lo capte.  Si el paquete ``redis`` no
    está instalado, se hace fallback silencioso con un warning.
    """
    try:
        from config import settings

        if not settings.REDIS_URL:
            return _MemoryBackend()

        backend = _RedisBackend(settings.REDIS_URL, namespace=namespace)
        log.info("shared_cache_redis_connected", namespace=namespace)
        return backend
    except ImportError as exc:
        log.warning(
            "shared_cache_redis_module_missing",
            error=str(exc),
            fallback="memory",
        )
        return _MemoryBackend()
    except Exception as exc:
        log.error(
            "shared_cache_redis_unavailable",
            error=str(exc),
            env=os.getenv("ENV", ""),
            fallback="memory",
        )
        return _MemoryBackend()


def reset_cache(namespace: str | None = None) -> None:
    """Elimina instancias del singleton (útil en tests o tras cambio de config).

    Args:
        namespace: Si se da, elimina solo ese namespace. Si None, elimina todos.
    """
    global _redis_available
    with _instances_lock:
        if namespace is None:
            _instances.clear()
            _redis_available = None
        else:
            _instances.pop(namespace, None)


# ---------------------------------------------------------------------------
# Decorador de cache para endpoints (con protección anti-estampida)
# ---------------------------------------------------------------------------

T = TypeVar("T")
_CACHE_LOCKS_MAX_SIZE = 1024  # LRU global — ver docstring de _get_cache_lock
_cache_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
_cache_locks_mutex = threading.Lock()


def _get_cache_lock(key: str) -> asyncio.Lock:
    """Obtiene (o crea) un ``asyncio.Lock`` por *key* de forma thread-safe.

    LRU-acotado a ``_CACHE_LOCKS_MAX_SIZE``: sin esto, cada combinación
    distinta de filtros que llega a un endpoint cacheado deja un ``Lock``
    vivo para siempre en este dict aunque su entrada ya haya expirado y sido
    evictada de ``_MemoryBackend`` — un memory leak que crece con el uptime
    del proceso, no con el volumen de datos. Evictar el lock menos usado no
    rompe la protección anti-estampida de una request ya en vuelo (esa
    coroutine ya tiene su propia referencia al ``Lock``); en el peor caso,
    una nueva request para la misma key llegada justo después de la eviction
    obtiene un ``Lock`` distinto y no queda deduplicada — mismo trade-off que
    la eviction LRU del caché de datos.
    """
    with _cache_locks_mutex:
        lock = _cache_locks.get(key)
        if lock is not None:
            _cache_locks.move_to_end(key)
            return lock
        if len(_cache_locks) >= _CACHE_LOCKS_MAX_SIZE:
            _cache_locks.popitem(last=False)
        lock = asyncio.Lock()
        _cache_locks[key] = lock
        return lock


def cache_response(
    ttl: int = 300,
    namespace: str = "analytics",
) -> Callable[..., Any]:
    """Decorador que cachea respuestas de endpoints FastAPI.

    Características:
      - **Anti-estampida**: usa ``asyncio.Lock`` por clave para que si
        N peticiones idénticas llegan simultáneamente, solo 1 ejecute la
        función pesada y las demás esperen el resultado cacheado.
      - **Async-native**: el wrapper es ``async def``, lo que evita que
        FastAPI despache la llamada al threadpool *antes* de revisar caché.
        Si la función subyacente es síncrona, se ejecuta con
        ``anyio.to_thread.run_sync`` **dentro** del lock.
      - Compatible con funciones que devuelven ``pydantic.BaseModel`` (se
        cachea como dict vía ``model_dump()``).

    Args:
        ttl: Tiempo de vida en segundos (default 5 min).
        namespace: Namespace del backend de cache.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        is_sync = not inspect.iscoroutinefunction(func)

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            cache = get_cache(namespace)

            # --- Build cache key ---
            key_parts = [func.__name__]
            for k, v in sorted(kwargs.items()):
                if k.startswith("_"):
                    # Skip private/internal args like _user dependency
                    continue
                if isinstance(v, BaseModel):
                    key_parts.append(f"{k}:{v.model_dump_json(exclude_none=True)}")
                elif v is not None:
                    key_parts.append(f"{k}:{v}")
            cache_key = "|".join(key_parts)

            # --- Fast path (no lock) ---
            cached = cache.get(cache_key)
            if cached is not None:
                log.debug("cache_hit", key=cache_key, func=func.__name__)
                return cached

            # --- Stampede-protected slow path ---
            lock = _get_cache_lock(cache_key)
            async with lock:
                # Double-check inside lock
                cached = cache.get(cache_key)
                if cached is not None:
                    log.debug("cache_hit_after_lock", key=cache_key, func=func.__name__)
                    return cached

                log.debug("cache_miss", key=cache_key, func=func.__name__)
                if is_sync:
                    import anyio.to_thread

                    result = await anyio.to_thread.run_sync(
                        functools.partial(func, *args, **kwargs),
                    )
                else:
                    result = await func(*args, **kwargs)

                # Serialize Pydantic → dict for cache backends
                val = result.model_dump() if isinstance(result, BaseModel) else result
                cache.set(cache_key, val, ttl=ttl)
                return result

        return wrapper

    return decorator
