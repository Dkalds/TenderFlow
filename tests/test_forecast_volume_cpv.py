"""Previsión de volumen por CPV (RFC ux-tendencias-cpv #1).

La previsión que se superponía a las series de Tendencias CPV era la del
mercado entero. Estos tests fijan que el CPV pedido llega al repositorio con la
misma comparación que construye la serie de ese CPV, que la respuesta declara
el ámbito que realmente se usó, y que la ruta acota el parámetro.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

import services.analytics.forecast_svc as f_mod
from services.analytics.forecast_svc import ForecastFilters, get_forecast_volume


class _RepoFalso:
    def __init__(self, filas: list[dict[str, Any]]) -> None:
        self.filas = filas
        self.filtros: Any = None

    def forecast_monthly(self, filters: Any, *, metric: str) -> list[dict[str, Any]]:
        self.filtros = filters
        return self.filas


def _serie(meses: int) -> list[dict[str, Any]]:
    return [
        {"mes": f"{2024 + i // 12}-{i % 12 + 1:02d}", "valor": 10 + i % 5} for i in range(meses)
    ]


def test_el_cpv_llega_al_repositorio_y_vuelve_en_la_respuesta(monkeypatch):
    repo = _RepoFalso(_serie(24))
    monkeypatch.setattr(f_mod, "_repo", repo)

    res = get_forecast_volume(ForecastFilters(months_ahead=3, cpv="72267100"))

    assert repo.filtros.cpv == "72267100"
    assert res.cpv == "72267100"
    assert any(p.tipo == "forecast" for p in res.series)


def test_sin_cpv_es_la_prevision_global(monkeypatch):
    repo = _RepoFalso(_serie(24))
    monkeypatch.setattr(f_mod, "_repo", repo)

    res = get_forecast_volume(ForecastFilters(months_ahead=3))

    assert repo.filtros.cpv is None
    assert res.cpv is None


def test_cpv_sin_historia_devuelve_serie_vacia_con_su_ambito(monkeypatch):
    monkeypatch.setattr(f_mod, "_repo", _RepoFalso([]))
    res = get_forecast_volume(ForecastFilters(cpv="99999999"))
    assert res.series == []
    assert res.cpv == "99999999"


def _patron_cpv() -> str:
    from api.routes.analytics import forecast_volume_endpoint

    ruta = getattr(forecast_volume_endpoint, "__wrapped__", forecast_volume_endpoint)
    import inspect

    default = inspect.signature(ruta).parameters["cpv"].default
    for meta in default.metadata:
        if getattr(meta, "pattern", None):
            return str(meta.pattern)
    raise AssertionError("el parámetro cpv no declara patrón")


@pytest.mark.parametrize("valor", ["72267100", "72267100-4"])
def test_la_ruta_acepta_cpv_de_ocho_digitos(valor):
    assert re.fullmatch(_patron_cpv(), valor)


@pytest.mark.parametrize("valor", ["72", "7226710%", "72267100-45", "abc", "72267100' OR 1=1"])
def test_la_ruta_rechaza_cpv_fuera_de_forma(valor):
    assert not re.fullmatch(_patron_cpv(), valor)
