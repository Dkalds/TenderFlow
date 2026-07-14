"""Tests para services/_data_cache.SignalAwareCache."""

from __future__ import annotations

import threading
import time

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
