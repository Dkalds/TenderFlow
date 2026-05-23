"""Cache de respuestas para la API REST.

Delega a :mod:`shared.cache` — backend unificado LRU+TTL con soporte Redis.

Uso::

    from api.cache import cache_get, cache_set, cache_delete, cache_key, cache_clear_all

    key = cache_key("meta", "filters")
    value = cache_get(key)
    if value is None:
        value = compute_expensive_thing()
        cache_set(key, value, ttl=300)
"""

from __future__ import annotations

import hashlib
from typing import Any

from shared.cache import get_cache

# Namespace propio de la API para evitar colisiones en Redis
_NAMESPACE = "api"


def _backend():
    return get_cache(_NAMESPACE)


# ── API pública ────────────────────────────────────────────────────────────────


def cache_get(key: str) -> Any | None:
    """Lee del cache (Redis si disponible, sino in-memory)."""
    return _backend().get(key)


def cache_set(key: str, value: Any, ttl: float = 60.0) -> None:
    """Escribe en el cache con TTL en segundos."""
    _backend().set(key, value, ttl=ttl)


def cache_delete(key: str) -> None:
    """Invalida una entrada del cache."""
    _backend().delete(key)


def cache_key(*parts: Any) -> str:
    """Genera una cache key determinista desde varios componentes."""
    raw = ":".join(str(p) for p in parts)
    return "licsap:" + hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def cache_clear_all() -> None:
    """Limpia todo el cache in-memory del namespace API (usado en tests)."""
    _backend().clear()
