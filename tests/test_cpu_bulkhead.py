"""Tests del carril CPU-bound de la analítica.

Es lo que permite dimensionar el threadpool general para carga IO-bound sin
repetir el incidente de CPU starvation que en su día lo dejó clavado en 4
hilos: la agregación pandas se acota aparte, no compitiendo con las lecturas.
"""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from shared import concurrency
from shared.cache import cache_response, get_cache


@pytest.fixture(autouse=True)
def _limiters_limpios():
    concurrency.reset_limiters()
    yield
    concurrency.reset_limiters()


class TestLimiterTokens:
    def test_reads_the_size_from_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config.settings import settings

        monkeypatch.setattr(settings, "API_CPU_BOUND_TOKENS", 3, raising=False)
        assert concurrency.cpu_limiter().total_tokens == 3

    def test_never_goes_below_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config.settings import settings

        monkeypatch.setattr(settings, "API_CPU_BOUND_TOKENS", 0, raising=False)
        assert concurrency.cpu_limiter().total_tokens == 1

    def test_falls_back_to_the_default_when_settings_are_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un fallo al leer settings no puede dejar sin bulkhead a la analítica."""
        import sys

        # `_limiter_tokens` importa settings dentro de la función; anular el
        # módulo hace que ese import falle, que es el caso que el except cubre.
        monkeypatch.setitem(sys.modules, "config.settings", None)

        assert concurrency._limiter_tokens("API_CPU_BOUND_TOKENS", 2) == 2


def _saltos_de_un_fallo(monkeypatch: pytest.MonkeyPatch, llamada: Any) -> list[Any]:
    """Limitadores de los saltos a hilo de un fallo de caché, y el resultado al final.

    La primera llamada a una función decorada calcula además la huella de su
    DTO (parte de la clave), una vez por proceso y en el pool general: no es el
    handler, y no es lo que miden estos tests. Por eso se llama una vez antes de
    espiar, se vacía la caché para forzar otro fallo y solo se cuentan los
    saltos de ese segundo.
    """
    import anyio.to_thread as to_thread_mod

    get_cache("analytics").clear()
    anyio.run(llamada)
    get_cache("analytics").clear()
    visto: list[Any] = []
    original = to_thread_mod.run_sync

    async def _espia(fn: Any, *args: Any, **kwargs: Any) -> Any:
        visto.append(kwargs.get("limiter"))
        return await original(fn, *args, **kwargs)

    monkeypatch.setattr(to_thread_mod, "run_sync", _espia)
    visto.append(anyio.run(llamada))
    return visto


class TestCacheResponseCpuBound:
    def test_cpu_bound_handler_runs_inside_the_cpu_bulkhead(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El handler marcado `cpu_bound` no consume el pool general."""

        @cache_response(ttl=60, namespace="analytics", cpu_bound=True)
        def _agregacion_pesada(*, q: str) -> dict[str, str]:
            return {"q": q}

        visto = _saltos_de_un_fallo(monkeypatch, lambda: _agregacion_pesada(q="pandas"))
        resultado = visto.pop()

        assert resultado == {"q": "pandas"}
        assert visto == [concurrency.cpu_limiter()]

    def test_default_handler_uses_the_general_pool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        @cache_response(ttl=60, namespace="analytics")
        def _lectura_barata(*, q: str) -> dict[str, str]:
            return {"q": q}

        visto = _saltos_de_un_fallo(monkeypatch, lambda: _lectura_barata(q="barata"))
        visto.pop()

        assert visto == [None], "una lectura barata no debe gastar slot del carril CPU"

    def test_cached_result_skips_the_bulkhead_entirely(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """El hit de caché no debe ni pedir turno en el limiter."""
        get_cache("analytics").clear()
        ejecuciones: list[int] = []

        @cache_response(ttl=60, namespace="analytics", cpu_bound=True)
        def _agregacion(*, q: str) -> dict[str, str]:
            ejecuciones.append(1)
            return {"q": q}

        anyio.run(lambda: _agregacion(q="misma"))
        anyio.run(lambda: _agregacion(q="misma"))

        assert len(ejecuciones) == 1
