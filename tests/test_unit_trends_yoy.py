"""La variación interanual de Tendencias no se inventa un «+0 %» ni se infla.

Hasta 2026-11 el backend devolvía ``0.0`` sin año previo y el frontend
calculaba la suya comparando doce meses contra una ventana más corta.
"""

from __future__ import annotations

from typing import Any

import pytest

from db.repositories.aggregates import LicitacionesFilters
from services.analytics import trends


def _con_ventanas(monkeypatch: pytest.MonkeyPatch, **vals: float) -> list[Any]:
    llamadas: list[Any] = []

    def falso(filtros: LicitacionesFilters, **kwargs: str) -> dict[str, float]:
        llamadas.append(filtros)
        return {"cnt_cur": 0.0, "cnt_prev": 0.0, "imp_cur": 0.0, "imp_prev": 0.0, **vals}

    monkeypatch.setattr(trends._repo, "trends_yoy", falso)
    return llamadas


def test_sin_ano_previo_no_hay_variacion(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_ventanas(monkeypatch, cnt_cur=10.0, imp_cur=500.0)
    assert trends._yoy_from_repo(LicitacionesFilters()) == (None, None)


def test_con_ano_previo_da_el_porcentaje(monkeypatch: pytest.MonkeyPatch) -> None:
    _con_ventanas(monkeypatch, cnt_cur=15.0, cnt_prev=10.0, imp_cur=50.0, imp_prev=100.0)
    assert trends._yoy_from_repo(LicitacionesFilters()) == (50.0, -50.0)


def test_una_fecha_hasta_en_el_pasado_no_da_un_menos_cien(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con el rango acabado hace meses, la ventana actual sale vacía: no es un -100 %."""
    _con_ventanas(monkeypatch, cnt_prev=10.0, imp_prev=100.0)
    assert trends._yoy_from_repo(LicitacionesFilters(fecha_hasta="2025-06-30")) == (None, None)


def test_una_fecha_desde_que_corta_el_ano_previo_no_compara(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llamadas = _con_ventanas(monkeypatch, cnt_cur=15.0, cnt_prev=10.0)
    assert trends._yoy_from_repo(LicitacionesFilters(fecha_desde="2099-01-01")) == (None, None)
    assert llamadas == []


def test_la_respuesta_conserva_yoy_y_da_la_variacion_aparte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`yoy_*` sigue siendo `number` (cambiarle el tipo rompe el contrato); el nulo va aparte."""
    _con_ventanas(monkeypatch, cnt_cur=10.0, imp_cur=500.0)
    monkeypatch.setattr(trends._repo, "trends_daily", lambda f: [])
    monkeypatch.setattr(trends._repo, "trends_heatmap", lambda f: [])
    monkeypatch.setattr(trends._repo, "trends_histogram", lambda f: [])

    resultado = trends.get_trends(trends.TrendsFilters())

    assert (resultado.yoy_count, resultado.yoy_importe) == (0.0, 0.0)
    assert (resultado.variacion_licitaciones, resultado.variacion_importe) == (None, None)
