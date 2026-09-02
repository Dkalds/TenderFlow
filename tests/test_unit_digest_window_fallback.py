"""La ventana matinal sin tzdata: se aproxima con el horario de invierno."""

from __future__ import annotations

import builtins
from datetime import UTC, datetime
from typing import Any

from scheduler.pipeline_runs import _es_ventana_matinal


def _sin_zoneinfo(monkeypatch: Any) -> None:
    """Hace que ``from zoneinfo import ZoneInfo`` falle dentro de la función."""
    real_import = builtins.__import__

    def _import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "zoneinfo":
            raise ImportError("sin tzdata")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _import)


def test_sin_tzdata_usa_utc_mas_una_hora(monkeypatch: Any) -> None:
    _sin_zoneinfo(monkeypatch)
    # 06:00 UTC → 07:00 con el +1 de invierno: dentro de la ventana.
    assert _es_ventana_matinal(datetime(2026, 1, 15, 6, 0, tzinfo=UTC)) is True
    # 04:00 UTC → 05:00: fuera. (Con tzdata y en verano habría sido 06:00 y dentro,
    # que es exactamente la imprecisión que se acepta como degradación.)
    assert _es_ventana_matinal(datetime(2026, 7, 15, 4, 0, tzinfo=UTC)) is False
