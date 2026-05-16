"""Cache de respuestas para la API REST.

Dos backends:
- **In-memory** (default): :class:`cachetools.TTLCache` por proceso.
  Eficiente para un único worker; no comparte estado entre workers.
- **Redis** (opcional): si ``REDIS_URL`` está configurado, usa Redis como
  backend compartido entre workers, con serialización JSON.

Uso::

    from api.cache import cached_response, invalidate

    # En un endpoint que devuelva datos estables
    @router.get("/meta/filters")
    async def meta_filters(...):
        cache_key = "meta:filters"
        cached = await cached_response(cache_key)
        if cached is not None:
            return cached  # Header X-Cache: HIT añadido por el decorador

        result = await run_db(...)
        await cached_response(cache_key, store=result, ttl=300)
        return result

El helper :func:`make_cache_response` envuelve el resultado en un
:class:`~fastapi.Response` con ``X-Cache: HIT|MISS`` y ``Cache-Control``.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# ── Backend in-memory ────────────────────────────────────────────────────────

_IN_MEMORY_CACHE: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
_CACHE_MAX_SIZE = 256  # max entries en memoria


def _memory_get(key: str) -> Any | None:
    entry = _IN_MEMORY_CACHE.get(key)
    if entry is None:
        return None
    value, expires_at = entry
    if time.monotonic() > expires_at:
        _IN_MEMORY_CACHE.pop(key, None)
        return None
    return value


def _memory_set(key: str, value: Any, ttl: float) -> None:
    # Eviction simple: si superamos el máximo, borrar 10% de entradas más antiguas
    if len(_IN_MEMORY_CACHE) >= _CACHE_MAX_SIZE:
        now = time.monotonic()
        expired = [k for k, (_, exp) in _IN_MEMORY_CACHE.items() if exp < now]
        for k in expired[:max(1, _CACHE_MAX_SIZE // 10)]:
            _IN_MEMORY_CACHE.pop(k, None)
    _IN_MEMORY_CACHE[key] = (value, time.monotonic() + ttl)


def _memory_delete(key: str) -> None:
    _IN_MEMORY_CACHE.pop(key, None)


def _memory_clear() -> None:
    _IN_MEMORY_CACHE.clear()


# ── Backend Redis ─────────────────────────────────────────────────────────────

_redis_client = None
_redis_checked = False


def _get_redis():
    global _redis_client, _redis_checked
    if _redis_checked:
        return _redis_client
    _redis_checked = True
    try:
        from config import settings

        if not settings.REDIS_URL:
            return None
        import redis as redis_lib  # type: ignore[import]

        _redis_client = redis_lib.from_url(
            settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2
        )
        _redis_client.ping()
        log.info("api_cache_redis_connected", url=settings.REDIS_URL.split("@")[-1])
    except Exception as exc:
        log.warning("api_cache_redis_unavailable", error=str(exc), fallback="in-memory")
        _redis_client = None
    return _redis_client


def _redis_get(key: str) -> Any | None:
    r = _get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        log.debug("api_cache_redis_get_error", key=key, error=str(exc))
        return None


def _redis_set(key: str, value: Any, ttl: float) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.setex(key, int(ttl), json.dumps(value, ensure_ascii=False, default=str))
    except Exception as exc:
        log.debug("api_cache_redis_set_error", key=key, error=str(exc))


def _redis_delete(key: str) -> None:
    r = _get_redis()
    if r is None:
        return
    try:
        r.delete(key)
    except Exception:
        pass


# ── API pública ───────────────────────────────────────────────────────────────


def cache_get(key: str) -> Any | None:
    """Lee del cache (Redis si disponible, sino in-memory)."""
    r = _get_redis()
    if r is not None:
        return _redis_get(key)
    return _memory_get(key)


def cache_set(key: str, value: Any, ttl: float = 60.0) -> None:
    """Escribe en el cache con TTL en segundos."""
    r = _get_redis()
    if r is not None:
        _redis_set(key, value, ttl)
    else:
        _memory_set(key, value, ttl)


def cache_delete(key: str) -> None:
    """Invalida una entrada del cache."""
    _redis_delete(key)
    _memory_delete(key)


def cache_key(*parts: Any) -> str:
    """Genera una cache key determinista desde varios componentes."""
    raw = ":".join(str(p) for p in parts)
    return "licsap:" + hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def cache_clear_all() -> None:
    """Limpia todo el cache in-memory (usado en tests)."""
    _memory_clear()
