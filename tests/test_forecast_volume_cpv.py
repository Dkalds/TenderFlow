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


def _historico(res: Any) -> dict[str, float]:
    return {p.mes: p.valor for p in res.series if p.tipo == "historico"}


def test_un_mes_sin_publicaciones_es_un_cero_y_no_desaparece(monkeypatch):
    """El GROUP BY no devuelve los meses vacíos: sin rellenar, la serie se encogía."""
    from datetime import date

    filas = [f for f in _serie(24) if f["mes"] != "2024-06"]
    monkeypatch.setattr(f_mod, "_repo", _RepoFalso(filas))

    hist = _historico(
        get_forecast_volume(ForecastFilters(months_ahead=3, fecha_hasta=date(2025, 12, 31)))
    )

    assert hist["2024-06"] == 0.0
    assert len(hist) == 24


def test_los_meses_vacios_finales_son_ceros_y_la_proyeccion_arranca_en_el_mes_en_curso(
    monkeypatch,
):
    """Sin publicaciones desde hace meses: esos meses cerrados valen 0, no se proyectan."""
    from datetime import UTC, datetime

    hoy = datetime.now(UTC)
    ordinal = hoy.year * 12 + hoy.month - 1
    # 24 meses con datos que acaban cinco meses antes del mes en curso.
    filas = [
        {"mes": f"{(ordinal - i) // 12:04d}-{(ordinal - i) % 12 + 1:02d}", "valor": 10}
        for i in range(28, 4, -1)
    ]
    monkeypatch.setattr(f_mod, "_repo", _RepoFalso(filas))

    res = get_forecast_volume(ForecastFilters(months_ahead=3))

    hist = _historico(res)
    ultimo_cerrado = f"{(ordinal - 1) // 12:04d}-{(ordinal - 1) % 12 + 1:02d}"
    assert hist[ultimo_cerrado] == 0.0
    assert len(hist) == 28
    assert next(p.mes for p in res.series if p.tipo == "forecast") == (
        f"{hoy.year:04d}-{hoy.month:02d}"
    )


def test_el_mes_en_curso_no_entra_como_ultima_observacion(monkeypatch):
    """Un mes a medias se lee como una caída y arrastra la proyección."""
    from datetime import UTC, datetime

    hoy = datetime.now(UTC)
    en_curso = f"{hoy.year:04d}-{hoy.month:02d}"
    ordinal = hoy.year * 12 + hoy.month - 1
    filas = [
        {"mes": f"{(ordinal - i) // 12:04d}-{(ordinal - i) % 12 + 1:02d}", "valor": 10}
        for i in range(24, -1, -1)
    ]
    assert filas[-1]["mes"] == en_curso
    monkeypatch.setattr(f_mod, "_repo", _RepoFalso(filas))

    res = get_forecast_volume(ForecastFilters(months_ahead=3))

    assert en_curso not in _historico(res)
    assert next(p.mes for p in res.series if p.tipo == "forecast") == en_curso


def test_un_fecha_hasta_a_mitad_de_mes_deja_fuera_ese_mes(monkeypatch):
    from datetime import date

    monkeypatch.setattr(f_mod, "_repo", _RepoFalso(_serie(24)))

    hist = _historico(
        get_forecast_volume(ForecastFilters(months_ahead=3, fecha_hasta=date(2025, 12, 15)))
    )

    assert "2025-12" not in hist
    assert "2025-11" in hist
