"""Cache backend para el dashboard.

Delega a :mod:`shared.cache` — backend unificado LRU+TTL con soporte Redis.

Uso::

    from dashboard.cache import get_cache

    cache = get_cache()
    cache.set("my_key", value, ttl=300)
    value = cache.get("my_key")  # None si expirado o no existe

La instancia es singleton por proceso.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from shared.cache import get_cache as _shared_get_cache
from shared.cache import reset_cache as _reset

if TYPE_CHECKING:
    from shared.cache import _MemoryBackend, _RedisBackend

# Namespace propio del dashboard para evitar colisiones en Redis
_NAMESPACE = "dashboard"


def get_cache() -> _MemoryBackend | _RedisBackend:
    """Devuelve la instancia singleton del cache del dashboard."""
    return _shared_get_cache(_NAMESPACE)


def reset_cache() -> None:
    """Reinicia el singleton (útil en tests)."""
    _reset(_NAMESPACE)
