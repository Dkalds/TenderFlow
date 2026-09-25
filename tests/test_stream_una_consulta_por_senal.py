"""SSE: con cada señal de ingesta, una consulta de novedades por proceso, no una por cliente.

Sin BD: el centinela y ``_fetch_recent`` se sustituyen por dobles que cuentan
llamadas. Lo que se fija:

- N clientes que despiertan por la misma señal comparten una consulta.
- La consulta compartida es la misma que haría cada cliente (mismo ``desde``
  y ``batch``): quien pide otra cosa tiene la suya.
- Una señal nueva nunca reutiliza la consulta de la anterior.
- Que un cliente se vaya no cancela la consulta de los demás.
- Heartbeat inicial, evento de cierre y autenticación siguen como estaban
  (``tests/test_stream_route.py``).
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from api.routes import stream
from api.routes.stream import _SignalWatcher


@pytest.fixture(autouse=True)
def reloj_fijo(monkeypatch: pytest.MonkeyPatch) -> float:
    """Reloj de pared fijo **solo** para ``api.routes.stream``.

    El ``desde`` de la consulta va al segundo. Con el reloj real, dos clientes
    que calculan su cursor a ambos lados de un cambio de segundo piden dos
    consultas distintas —correcto, y raro—, y el recuento de estos tests
    fallaría de vez en cuando. ``monotonic`` sigue siendo el real.
    """
    ahora = time.time()
    monkeypatch.setattr(
        stream,
        "time",
        SimpleNamespace(
            time=lambda: ahora,
            monotonic=time.monotonic,
            strftime=time.strftime,
            gmtime=time.gmtime,
        ),
    )
    return ahora


@pytest.fixture()
def consultas(monkeypatch: pytest.MonkeyPatch) -> list[tuple[float, int]]:
    """``_fetch_recent`` de mentira: registra cada consulta y tarda un poco."""
    registro: list[tuple[float, int]] = []

    def _fetch(since_ts: float, limit: int, *, ahora: float | None = None) -> list[dict[str, Any]]:
        registro.append((since_ts, limit))
        time.sleep(0.05)  # deja que el resto de clientes llegue con la consulta en vuelo
        return [{"id_externo": f"L-{i}"} for i in range(limit)]

    monkeypatch.setattr(stream, "_fetch_recent", _fetch)
    return registro


def test_n_clientes_de_la_misma_senal_comparten_una_consulta(
    consultas: list[tuple[float, int]],
) -> None:
    async def _prueba() -> list[list[dict[str, Any]]]:
        watcher = _SignalWatcher()
        watcher._generacion = 1
        return await asyncio.gather(*(watcher.recientes(0.0, 20) for _ in range(6)))

    resultados = asyncio.run(_prueba())

    assert len(consultas) == 1
    assert all(r == resultados[0] for r in resultados)
    assert len(resultados[0]) == 20


def test_quien_pide_otra_consulta_tiene_la_suya(
    consultas: list[tuple[float, int]], reloj_fijo: float
) -> None:
    ahora = reloj_fijo

    async def _prueba() -> None:
        watcher = _SignalWatcher()
        watcher._generacion = 1
        await asyncio.gather(
            watcher.recientes(0.0, 20),
            watcher.recientes(0.0, 20),
            watcher.recientes(0.0, 5),  # otro batch
            watcher.recientes(ahora - 60, 20),  # otro checkpoint
        )

    asyncio.run(_prueba())

    assert sorted(limit for _, limit in consultas) == [5, 20, 20]


def test_una_senal_nueva_no_reutiliza_la_consulta_anterior(
    consultas: list[tuple[float, int]],
) -> None:
    async def _prueba() -> None:
        watcher = _SignalWatcher()
        watcher._generacion = 1
        await watcher.recientes(0.0, 20)
        watcher._generacion = 2  # lo que hace `_run` al ver una marca nueva
        await watcher.recientes(0.0, 20)

    asyncio.run(_prueba())

    assert len(consultas) == 2


def test_el_resultado_no_se_reutiliza_pasado_su_plazo(
    consultas: list[tuple[float, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stream, "_LOTE_TTL_SECONDS", 0.0)

    async def _prueba() -> None:
        watcher = _SignalWatcher()
        watcher._generacion = 1
        await watcher.recientes(0.0, 20)
        await asyncio.sleep(0.01)
        await watcher.recientes(0.0, 20)

    asyncio.run(_prueba())

    assert len(consultas) == 2


def test_que_un_cliente_se_vaya_no_cancela_la_consulta_de_los_demas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    liberar = threading.Event()
    llamadas = {"n": 0}

    def _fetch(since_ts: float, limit: int, *, ahora: float | None = None) -> list[dict[str, Any]]:
        llamadas["n"] += 1
        liberar.wait(timeout=10)
        return [{"id_externo": "L-1"}]

    monkeypatch.setattr(stream, "_fetch_recent", _fetch)

    async def _prueba() -> list[dict[str, Any]]:
        watcher = _SignalWatcher()
        watcher._generacion = 1
        primero = asyncio.create_task(watcher.recientes(0.0, 20))
        segundo = asyncio.create_task(watcher.recientes(0.0, 20))
        await asyncio.sleep(0.05)
        primero.cancel()  # el cliente que lanzó la consulta se desconecta
        await asyncio.sleep(0)
        liberar.set()
        return await asyncio.wait_for(segundo, timeout=10)

    assert asyncio.run(_prueba()) == [{"id_externo": "L-1"}]
    assert llamadas["n"] == 1


def test_una_senal_ya_atendida_no_vuelve_a_despertar_al_cliente(reloj_fijo: float) -> None:
    """Con la marca del centinela adelantada respecto al reloj de la API, el
    cliente despertaba en cada vuelta y relanzaba la consulta sin esperar."""

    async def _prueba() -> tuple[float | None, float | None]:
        watcher = _SignalWatcher()
        watcher._signal_ts = reloj_fijo + 3600  # marca «del futuro»
        watcher._generacion = 4
        ya_atendida = await watcher.wait_for_signal(reloj_fijo, 0.05, generacion_servida=4)
        nueva = await watcher.wait_for_signal(reloj_fijo, 0.05, generacion_servida=3)
        return ya_atendida, nueva

    ya_atendida, nueva = asyncio.run(_prueba())

    assert ya_atendida is None
    assert nueva is not None


class _Peticion:
    def __init__(self) -> None:
        self.desconectada = False

    async def is_disconnected(self) -> bool:
        return self.desconectada


def test_de_extremo_a_extremo_n_conexiones_una_consulta(
    consultas: list[tuple[float, int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stream, "_POLL_INTERVAL", 0.02)
    monkeypatch.setattr(stream, "_HEARTBEAT_INTERVAL", 3600.0)
    monkeypatch.setattr(stream, "_MAX_DURATION_SECONDS", 20)
    monkeypatch.setattr("shared.cache_signal.get_signal_timestamp", lambda: 100.0)

    async def _cliente() -> list[str]:
        peticion = _Peticion()
        eventos: list[str] = []
        async for evento in stream._event_generator(peticion, 0.0, 20):  # type: ignore[arg-type]  # doble de Request
            eventos.append(evento)
            if evento.startswith("event: licitaciones_nuevas"):
                peticion.desconectada = True
        return eventos

    async def _prueba() -> list[list[str]]:
        return await asyncio.wait_for(asyncio.gather(*(_cliente() for _ in range(4))), timeout=30)

    por_cliente = asyncio.run(_prueba())

    assert len(consultas) == 1, f"{len(consultas)} consultas para 4 clientes"
    for eventos in por_cliente:
        assert eventos[0].startswith("event: heartbeat")
        assert any(e.startswith("event: licitaciones_nuevas") for e in eventos)
        assert eventos[-1].startswith("event: close")
