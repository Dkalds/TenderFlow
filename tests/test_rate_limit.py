"""Tests para dashboard/utils/rate_limit.py."""

from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def fake_streamlit(monkeypatch):
    """Mock mínimo de streamlit con session_state como dict y warning() no-op."""
    mod = types.ModuleType("streamlit")
    mod.session_state = {}  # type: ignore[attr-defined]
    mod.warning = lambda *a, **kw: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "streamlit", mod)
    # Forzar re-importación de rate_limit para que coja el mock fresco.
    # Hay que limpiar tanto sys.modules como el atributo en el paquete padre.
    sys.modules.pop("dashboard.utils.rate_limit", None)
    import dashboard.utils as _du
    if hasattr(_du, "rate_limit"):
        delattr(_du, "rate_limit")
    yield mod
    sys.modules.pop("dashboard.utils.rate_limit", None)
    if hasattr(_du, "rate_limit"):
        delattr(_du, "rate_limit")


def test_check_rate_limit_allows_under_threshold(fake_streamlit):
    from dashboard.utils.rate_limit import check_rate_limit

    for _ in range(5):
        assert check_rate_limit("op", max_calls=10, window_seconds=60) is True


def test_check_rate_limit_blocks_over_threshold(fake_streamlit):
    from dashboard.utils.rate_limit import check_rate_limit

    for _ in range(10):
        assert check_rate_limit("op", max_calls=10, window_seconds=60) is True
    # 11ª debería fallar
    assert check_rate_limit("op", max_calls=10, window_seconds=60) is False


def test_check_rate_limit_window_slides(fake_streamlit, monkeypatch):
    """Tras pasar la ventana, el contador se purga y permite nuevas llamadas."""
    import time as time_mod

    from dashboard.utils import rate_limit

    fake_now = [1000.0]

    def _now() -> float:
        return fake_now[0]

    monkeypatch.setattr(rate_limit.time, "monotonic", _now)

    # Llenar el bucket
    for _ in range(5):
        assert rate_limit.check_rate_limit("op", max_calls=5, window_seconds=10) is True
    assert rate_limit.check_rate_limit("op", max_calls=5, window_seconds=10) is False

    # Avanzar el reloj más allá de la ventana
    fake_now[0] += 11
    # Ahora debería permitir de nuevo
    assert rate_limit.check_rate_limit("op", max_calls=5, window_seconds=10) is True


def test_get_call_count_reflects_calls(fake_streamlit):
    from dashboard.utils.rate_limit import check_rate_limit, get_call_count

    assert get_call_count("op") == 0
    check_rate_limit("op", max_calls=10, window_seconds=60)
    check_rate_limit("op", max_calls=10, window_seconds=60)
    assert get_call_count("op") == 2


def test_reset_clears_counter(fake_streamlit):
    from dashboard.utils.rate_limit import check_rate_limit, get_call_count, reset

    for _ in range(3):
        check_rate_limit("op", max_calls=10, window_seconds=60)
    assert get_call_count("op") == 3
    reset("op")
    assert get_call_count("op") == 0


def test_distinct_keys_have_independent_counters(fake_streamlit):
    from dashboard.utils.rate_limit import check_rate_limit

    for _ in range(5):
        check_rate_limit("op_a", max_calls=5, window_seconds=60)
    # op_a llena, pero op_b sigue libre
    assert check_rate_limit("op_a", max_calls=5, window_seconds=60) is False
    assert check_rate_limit("op_b", max_calls=5, window_seconds=60) is True


def test_throttled_returns_true_under_limit(fake_streamlit):
    from dashboard.utils.rate_limit import throttled

    assert throttled("op", max_calls=5, window_seconds=60) is True


def test_throttled_returns_false_over_limit(fake_streamlit):
    from dashboard.utils.rate_limit import throttled

    for _ in range(5):
        throttled("op", max_calls=5, window_seconds=60)
    assert throttled("op", max_calls=5, window_seconds=60) is False
