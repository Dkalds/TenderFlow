"""Tests para services/_data_cache.SignalAwareCache."""

from __future__ import annotations

import gc
import threading
import time
import weakref

from services._data_cache import SignalAwareCache


def test_caches_value_between_calls():
    calls = {"n": 0}

    def loader() -> int:
        calls["n"] += 1
        return 42

    cache: SignalAwareCache[int] = SignalAwareCache(ttl=60.0)
    assert cache.get(loader) == 42
    assert cache.get(loader) == 42
    # El loader solo se llamó una vez
    assert calls["n"] == 1


def test_clear_forces_reload():
    calls = {"n": 0}

    def loader() -> int:
        calls["n"] += 1
        return calls["n"]

    cache: SignalAwareCache[int] = SignalAwareCache(ttl=60.0)
    assert cache.get(loader) == 1
    cache.clear()
    assert cache.get(loader) == 2
    assert calls["n"] == 2


def test_ttl_zero_always_reloads():
    calls = {"n": 0}

    def loader() -> int:
        calls["n"] += 1
        return calls["n"]

    cache: SignalAwareCache[int] = SignalAwareCache(ttl=0.0)
    cache.get(loader)
    cache.get(loader)
    assert calls["n"] == 2


def test_signal_invalidates_cache(monkeypatch):
    """Una señal de ingesta más reciente que la carga fuerza recarga."""
    fake_ts = {"value": 100.0}

    def fake_signal() -> float:
        return fake_ts["value"]

    monkeypatch.setattr("services._data_cache.get_signal_timestamp", fake_signal)

    calls = {"n": 0}

    def loader() -> int:
        calls["n"] += 1
        return calls["n"]

    cache: SignalAwareCache[int] = SignalAwareCache(ttl=600.0)
    assert cache.get(loader) == 1  # carga con signal_ts=100
    assert cache.get(loader) == 1  # signal sin cambios → cacheado

    # Llega una nueva ingesta (timestamp avanza)
    fake_ts["value"] = 200.0
    assert cache.get(loader) == 2  # invalidado por señal
    assert calls["n"] == 2


def test_previous_value_released_before_loader_runs():
    """El valor viejo se suelta ANTES de construir el nuevo.

    Regresión de memoria: estas cachés guardan cargas full-table. Si la
    instancia cacheada sigue referenciada mientras ``loader()`` construye su
    reemplazo, las dos coexisten y cada refresco pica al doble del tamaño de la
    caché — con el TTL de 60 s, una vez por minuto bajo tráfico.
    """
    observed_during_load: list[object] = []

    def loader() -> list[int]:
        observed_during_load.append(cache._value)
        return [1, 2, 3]

    cache: SignalAwareCache[list[int]] = SignalAwareCache(ttl=0.0)
    assert cache.get(loader) == [1, 2, 3]
    assert cache.get(loader) == [1, 2, 3]

    # En ambas cargas (la fría y el refresco) la caché no retenía nada.
    assert observed_during_load == [None, None]


def test_previous_value_is_collectable_while_the_loader_runs():
    """Ninguna referencia al valor viejo sobrevive a la llamada al loader.

    Más estricto que el test anterior: no basta con vaciar el atributo, porque
    el local del propio ``get()`` también mantiene vivo el objeto durante toda
    la construcción del reemplazo — que es justo el pico que se quiere evitar.
    """

    class Payload:
        """Sustituto de la carga full-table (weakref-able)."""

    cache: SignalAwareCache[Payload] = SignalAwareCache(ttl=0.0)
    cache.get(Payload)
    ref = weakref.ref(cache._value)

    still_alive: list[bool] = []

    def rebuild() -> Payload:
        gc.collect()
        still_alive.append(ref() is not None)
        return Payload()

    cache.get(rebuild)
    assert still_alive == [False]


def test_stale_reader_racing_a_refresh_never_gets_none():
    """El camino rápido no puede devolver el ``None`` transitorio del refresco."""
    cache: SignalAwareCache[str] = SignalAwareCache(ttl=600.0)
    assert cache.get(lambda: "v1") == "v1"

    # Simula el hueco en que un refresco ya soltó el valor pero aún no lo
    # reemplazó, con _valid todavía en True (lo que ve un lector sin lock).
    cache._value = None
    assert cache.get(lambda: "v2") == "v2"


def test_concurrent_miss_calls_loader_once():
    """N threads con caché fría no deben construir el valor en paralelo.

    Regresión: sin lock, cada thread llamaba a loader() de forma independiente
    (postmortem OOM Render 2026-07-14 — 5 endpoints de analytics reconstruyendo
    el DataFrame full-table al mismo tiempo tras un reinicio en frío).
    """
    calls = {"n": 0}
    lock = threading.Lock()

    def loader() -> int:
        with lock:
            calls["n"] += 1
        time.sleep(0.05)
        return 42

    cache: SignalAwareCache[int] = SignalAwareCache(ttl=60.0)
    threads = [threading.Thread(target=cache.get, args=(loader,)) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["n"] == 1
