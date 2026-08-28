"""Helpers de concurrencia para la API REST.

El driver de Postgres (psycopg3) es síncrono. Para no bloquear el event loop
de FastAPI (async), toda query lanzada desde un handler ``async`` debe
ejecutarse en el threadpool de anyio con ``run_db``.
``tests/test_async_handlers_no_blocking_io.py`` lo verifica de forma
estructural sobre ``api/routes/``.

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

from anyio import CapacityLimiter, to_thread

# Los presupuestos viven en ``shared`` para que ``shared.cache`` pueda usarlos
# sin importar ``api`` (inversión de capas) y para que ambos caminos compartan
# el mismo limiter.
from shared.concurrency import cpu_limiter, ml_limiter, reset_limiters

T = TypeVar("T")

__all__ = [
    "cpu_limiter",
    "ml_limiter",
    "reset_limiters",
    "run_cpu",
    "run_db",
    "run_io",
    "run_ml",
    "run_probe",
]

# Los bulkheads de ML y CPU viven en ``shared.concurrency`` porque los comparte
# ``shared.cache``. El de sondeos se queda aquí: solo lo usa ``/health``, su
# tamaño es fijo (no sale de settings) y nada fuera de ``api`` lo necesita.
_PROBE_LIMITER: CapacityLimiter | None = None


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


def _get_probe_limiter() -> CapacityLimiter:
    """Lazy singleton del CapacityLimiter para sondeos de salud."""
    global _PROBE_LIMITER
    if _PROBE_LIMITER is None:
        _PROBE_LIMITER = CapacityLimiter(4)
    return _PROBE_LIMITER


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


async def run_probe(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta un sondeo de salud en un threadpool propio, **abandonable**.

    Diferencia esencial con ``run_db``: ``abandon_on_cancel=True``. Por defecto,
    ``to_thread.run_sync`` NO devuelve el control al cancelarse — espera a que
    el hilo termine —, así que envolverlo en ``anyio.fail_after`` no acota nada:
    con la BD colgada, ``/health`` seguía tardando lo que tardase el sondeo. Con
    esta bandera el timeout sí devuelve y el endpoint puede responder
    ``degraded`` mientras el hilo huérfano se apaga solo (lo hará: la conexión
    lleva ``connect_timeout`` y ``statement_timeout`` propios).

    El limiter dedicado es la contrapartida: un hilo abandonado retiene su slot
    hasta morir, y sin bulkhead una racha de probes con la BD caída se comería
    el threadpool general que sirve al resto de la API. Mismo patrón que
    ``run_ml``.
    """
    limiter = _get_probe_limiter()
    return await to_thread.run_sync(
        lambda: fn(*args, **kwargs), limiter=limiter, abandon_on_cancel=True
    )


async def run_io(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Ejecuta I/O de red **síncrona** (SMTP, HTTP saliente) en el threadpool.

    Mismo mecanismo que ``run_db`` y misma razón —no bloquear el event loop—
    pero con su propio span: etiquetar un envío de correo como ``db.query``
    ensucia las trazas justo donde se investiga una latencia, y un día alguien
    buscará por qué una "query" tarda quince segundos y encontrará un SMTP.

    Sin bulkhead propio a propósito: hoy el único uso es un correo puntual
    disparado a mano por un administrador, no un camino de tráfico. Si aparece
    I/O de red en un endpoint caliente, merecerá su ``CapacityLimiter`` como
    lo tienen ``run_ml`` y ``run_cpu``.
    """
    with _span("io.task", {"io.function": _fn_name(fn)}):
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
