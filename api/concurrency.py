"""Helpers de concurrencia para la API REST.

El driver de Postgres (psycopg3) es síncrono. Para no bloquear el event loop
de FastAPI (async), toda query lanzada desde un handler ``async`` debe
ejecutarse en el threadpool de anyio con ``run_db``.

Bulkhead pattern
----------------
La inferencia ML (``/explain``, ``/feedback/queue``) puede tardar varios
segundos y bloquear hilos del pool general. ``run_ml`` usa un
:class:`~anyio.CapacityLimiter` dedicado (``API_ML_TOKENS``) para aislar esa
carga del resto de handlers. ``run_cpu`` hace lo propio con la analítica
pandas (``API_CPU_BOUND_TOKENS``): sin ese carril, un puñado de peticiones a
``/analytics/competitors`` satura el pool general y tumba la API entera —
que es el incidente que en 2026-08 llevó a fijar el límite global en 4.

OTEL instrumentation
--------------------
Si OpenTelemetry está configurado, ``run_db`` crea un span ``db.query`` con
el nombre de la función como atributo. Overhead nulo si OTEL no está
configurado (NoOp tracer).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from typing import Any, TypeVar

from anyio import to_thread

# Los presupuestos viven en ``shared`` para que ``shared.cache`` pueda usarlos
# sin importar ``api`` (inversión de capas) y para que ambos caminos compartan
# el mismo limiter.
from shared.concurrency import cpu_limiter, ml_limiter, reset_limiters

T = TypeVar("T")

__all__ = ["cpu_limiter", "ml_limiter", "reset_limiters", "run_cpu", "run_db", "run_ml"]


def _span(name: str, attributes: dict[str, str]) -> AbstractContextManager[Any]:
    """Context manager del span OTEL, o ``nullcontext`` si el tracer falla.

    El try/except cubre **solo** la obtención del tracer. Hasta 2026-08
    envolvía también el ``await`` de la función de trabajo, así que cualquier
    excepción de ``fn`` caía en el ``except`` y la ejecutaba por segunda vez:
    en las rutas de escritura eso era un efecto lateral duplicado, y el
    traceback que llegaba al handler era el del segundo intento.
    """
    try:
        from observability.tracing import get_tracer

        span: AbstractContextManager[Any] = get_tracer("api.concurrency").start_as_current_span(
            name, attributes=attributes
        )
    except Exception:
        return nullcontext()
    return span


def _fn_name(fn: Callable[..., Any]) -> str:
    name: str = getattr(fn, "__name__", repr(fn))
    return name


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta ``fn(*args, **kwargs)`` en el threadpool general de anyio.

    Crea un span OTEL ``db.query`` con el nombre de la función si OTEL
    está configurado; no-op si no lo está. ``fn`` se ejecuta exactamente una
    vez: si lanza, la excepción se propaga sin reintento.

    Uso::

        items, total = await run_db(repo.list_paginated, q=q, limit=limit)
    """
    with _span("db.query", {"db.function": _fn_name(fn)}):
        return await to_thread.run_sync(lambda: fn(*args, **kwargs))


async def run_ml(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta ``fn(*args, **kwargs)`` en el threadpool ML dedicado (bulkhead).

    Usa un :class:`~anyio.CapacityLimiter` para evitar que la inferencia ML
    sature el pool general. Las requests que excedan el límite esperan
    (back-pressure natural). ``fn`` se ejecuta exactamente una vez.

    Uso::

        probs = await run_ml(classifier.predict_proba, texts)
    """
    with _span("ml.inference", {"ml.function": _fn_name(fn)}):
        return await to_thread.run_sync(lambda: fn(*args, **kwargs), limiter=ml_limiter())


async def run_cpu(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta ``fn`` en el carril CPU-bound (analítica pandas).

    Mismo bulkhead que ``run_ml`` pero con su propio presupuesto: la analítica
    y la inferencia compiten por CPU, no por conexiones, y saturar el pool
    general con ellas deja sin hilos a las lecturas baratas.
    """
    with _span("cpu.task", {"cpu.function": _fn_name(fn)}):
        return await to_thread.run_sync(lambda: fn(*args, **kwargs), limiter=cpu_limiter())
