"""Cache unificado con backends Memory (LRU+TTL) y Redis.

Reemplaza ``api/cache.py`` y ``dashboard/cache.py`` con una única implementación
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

import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any

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
        namespace: Identificador lógico del cache (ej. "api", "dashboard").
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

    En producción (``ENV=prod``), lanza ``RuntimeError`` si Redis no está
    disponible — el cache compartido es obligatorio para coherencia entre
    procesos. Si el paquete ``redis`` no está instalado, se hace fallback
    silencioso a MemoryBackend con un warning (deploy sin Redis).
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
        if os.getenv("ENV", "").lower() == "prod":
            raise RuntimeError(
                f"Redis no disponible en producción (REDIS_URL configurado pero "
                f"la conexión falló): {exc}"
            ) from exc
        log.info("shared_cache_redis_unavailable", error=str(exc), fallback="memory")
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
