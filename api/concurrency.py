"""Helpers de concurrencia para la API REST.

SQLite es síncrono. Para no bloquear el event loop de FastAPI (async),
toda query debe ejecutarse en el threadpool de anyio con ``run_db``.

Bulkhead pattern
----------------
La inferencia ML (``/explain``, ``/feedback/queue``) puede tardar varios
segundos y bloquear hilos del pool general. ``run_ml`` usa un
:class:`~anyio.CapacityLimiter` dedicado de 2 slots para aislar esa carga
del resto de handlers.

OTEL instrumentation
--------------------
Si OpenTelemetry está configurado, ``run_db`` crea un span ``db.query``
con el nombre de la función como atributo. Overhead nulo si OTEL no está
configurado (NoOp tracer).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from anyio import CapacityLimiter, to_thread

T = TypeVar("T")

# Pool general para queries DB (sin límite explícito — usa el default de anyio)
# Pool dedicado para inferencia ML — máx. 2 requests concurrentes de ML
_ML_LIMITER: CapacityLimiter | None = None


def _get_ml_limiter() -> CapacityLimiter:
    """Lazy singleton del CapacityLimiter para ML. Creado al primer uso."""
    global _ML_LIMITER
    if _ML_LIMITER is None:
        _ML_LIMITER = CapacityLimiter(2)
    return _ML_LIMITER


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta ``fn(*args, **kwargs)`` en el threadpool general de anyio.

    Crea un span OTEL ``db.query`` con el nombre de la función si OTEL
    está configurado; no-op si no lo está.

    Uso::

        items, total = await run_db(repo.list_paginated, q=q, limit=limit)
    """
    _fn_name = getattr(fn, "__name__", repr(fn))
    try:
        from observability.tracing import get_tracer

        tracer = get_tracer("api.concurrency")
        with tracer.start_as_current_span(
            "db.query",
            attributes={"db.function": _fn_name},
        ):
            return await to_thread.run_sync(lambda: fn(*args, **kwargs))
    except Exception:
        # Fallback sin tracing si hay cualquier problema con OTEL
        return await to_thread.run_sync(lambda: fn(*args, **kwargs))


async def run_ml(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta ``fn(*args, **kwargs)`` en el threadpool ML dedicado (bulkhead).

    Usa un :class:`~anyio.CapacityLimiter` de 2 slots para evitar que la
    inferencia ML sature el pool general de DB. Las requests que excedan el
    límite esperan (back-pressure natural).

    Crea un span OTEL ``ml.inference`` si OTEL está configurado.

    Uso::

        probs = await run_ml(classifier.predict_proba, texts)
    """
    _fn_name = getattr(fn, "__name__", repr(fn))
    limiter = _get_ml_limiter()
    try:
        from observability.tracing import get_tracer

        tracer = get_tracer("api.concurrency")
        with tracer.start_as_current_span(
            "ml.inference",
            attributes={"ml.function": _fn_name},
        ):
            return await to_thread.run_sync(lambda: fn(*args, **kwargs), limiter=limiter)
    except Exception:
        return await to_thread.run_sync(lambda: fn(*args, **kwargs), limiter=limiter)
