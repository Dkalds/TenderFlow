"""Helpers de concurrencia para la API REST.

SQLite es síncrono. Para no bloquear el event loop de FastAPI (async),
toda query debe ejecutarse en el threadpool de anyio con ``run_db``.

Bulkhead pattern
----------------
La inferencia ML (``/explain``, ``/feedback/queue``) puede tardar varios
segundos y bloquear hilos del pool general. ``run_ml`` usa un
:class:`~anyio.CapacityLimiter` dedicado de 2 slots para aislar esa carga
del resto de handlers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from anyio import CapacityLimiter, to_thread

# Pool general para queries DB (sin límite explícito — usa el default de anyio)
# Pool dedicado para inferencia ML — máx. 2 requests concurrentes de ML
_ML_LIMITER: CapacityLimiter | None = None


def _get_ml_limiter() -> CapacityLimiter:
    """Lazy singleton del CapacityLimiter para ML. Creado al primer uso."""
    global _ML_LIMITER
    if _ML_LIMITER is None:
        _ML_LIMITER = CapacityLimiter(2)
    return _ML_LIMITER


async def run_db[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta ``fn(*args, **kwargs)`` en el threadpool general de anyio.

    Uso::

        items, total = await run_db(repo.list_paginated, q=q, limit=limit)
    """
    return await to_thread.run_sync(lambda: fn(*args, **kwargs))


async def run_ml[T](fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta ``fn(*args, **kwargs)`` en el threadpool ML dedicado (bulkhead).

    Usa un :class:`~anyio.CapacityLimiter` de 2 slots para evitar que la
    inferencia ML sature el pool general de DB. Las requests que excedan el
    límite esperan (back-pressure natural).

    Uso::

        probs = await run_ml(classifier.predict_proba, texts)
    """
    limiter = _get_ml_limiter()
    return await to_thread.run_sync(lambda: fn(*args, **kwargs), limiter=limiter)
