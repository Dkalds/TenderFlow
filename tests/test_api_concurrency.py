"""Tests de ``api.concurrency`` — los helpers de threadpool de la API.

El foco es que ``fn`` se ejecute **exactamente una vez**. Hasta 2026-08 el
try/except que cubría el fallback de OpenTelemetry envolvía también el
``await`` de la función de trabajo, así que cualquier excepción de ``fn`` caía
en el ``except`` y la ejecutaba por segunda vez. En rutas de escritura
(descartes del Radar, watchlist, pursuits, notificaciones) eso significa un
efecto lateral duplicado ante el primer fallo transitorio.
"""

from __future__ import annotations

import anyio
import pytest

from api import concurrency


class _Boom(Exception):
    pass


def test_run_db_executes_once_on_success() -> None:
    calls: list[int] = []

    def _work() -> str:
        calls.append(1)
        return "ok"

    assert anyio.run(concurrency.run_db, _work) == "ok"
    assert len(calls) == 1


def test_run_db_executes_once_when_fn_raises() -> None:
    """Regresión: una excepción de ``fn`` no debe provocar un segundo intento."""
    calls: list[int] = []

    def _work() -> None:
        calls.append(1)
        raise _Boom("fallo transitorio")

    async def _main() -> None:
        with pytest.raises(_Boom):
            await concurrency.run_db(_work)

    anyio.run(_main)
    assert len(calls) == 1, "run_db reintentó la función tras la excepción"


def test_run_db_propagates_original_exception() -> None:
    """El traceback que llega al handler es el del único intento."""

    def _work() -> None:
        raise _Boom("mensaje original")

    async def _main() -> None:
        with pytest.raises(_Boom, match="mensaje original"):
            await concurrency.run_db(_work)

    anyio.run(_main)


def test_run_ml_executes_once_when_fn_raises() -> None:
    calls: list[int] = []

    def _work() -> None:
        calls.append(1)
        raise _Boom("inferencia rota")

    async def _main() -> None:
        with pytest.raises(_Boom):
            await concurrency.run_ml(_work)

    anyio.run(_main)
    assert len(calls) == 1


def test_run_cpu_executes_once_when_fn_raises() -> None:
    calls: list[int] = []

    def _work() -> None:
        calls.append(1)
        raise _Boom("pandas roto")

    async def _main() -> None:
        with pytest.raises(_Boom):
            await concurrency.run_cpu(_work)

    anyio.run(_main)
    assert len(calls) == 1


def test_run_db_survives_a_broken_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si OTEL falla al dar el tracer, el trabajo sigue ejecutándose una vez."""
    calls: list[int] = []

    def _explode(_name: str) -> object:
        raise RuntimeError("otel mal configurado")

    monkeypatch.setattr("observability.tracing.get_tracer", _explode)

    def _work() -> str:
        calls.append(1)
        return "ok"

    assert anyio.run(concurrency.run_db, _work) == "ok"
    assert len(calls) == 1


def test_bulkheads_are_independent() -> None:
    """ML y CPU tienen presupuestos separados, no comparten limiter."""
    concurrency.reset_limiters()
    assert concurrency.ml_limiter() is not concurrency.cpu_limiter()


def test_cache_response_shares_the_cpu_bulkhead() -> None:
    """``shared.cache`` y ``api.concurrency`` deben usar el MISMO limiter.

    Si cada uno creara el suyo, dos presupuestos de 2 slots permitirían 4
    agregaciones pandas concurrentes en vez de 2.
    """
    from shared.concurrency import cpu_limiter as shared_cpu_limiter

    concurrency.reset_limiters()
    assert concurrency.cpu_limiter() is shared_cpu_limiter()


def test_run_cpu_passes_its_own_limiter() -> None:
    """``run_cpu`` no debe consumir slots del bulkhead de ML."""
    concurrency.reset_limiters()
    cpu_limiter = concurrency.cpu_limiter()
    seen: list[object] = []

    async def _fake_run_sync(fn: object, **kwargs: object) -> str:
        seen.append(kwargs.get("limiter"))
        return "ok"

    async def _main() -> None:
        import api.concurrency as mod

        original = mod.to_thread.run_sync
        mod.to_thread.run_sync = _fake_run_sync  # type: ignore[assignment]
        try:
            await mod.run_cpu(lambda: "ok")
        finally:
            mod.to_thread.run_sync = original  # type: ignore[assignment]

    anyio.run(_main)
    assert seen == [cpu_limiter]
