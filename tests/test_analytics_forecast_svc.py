"""Tests unitarios para services/analytics/forecast_svc.

Parchea load_stats_dataframe y load_raw_adjudicaciones con filas sintéticas;
el motor real (forecast_volume / build_forecast_df) corre sin mocks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from services.analytics.forecast_svc import (
    ForecastFilters,
    RetenderingFilters,
    get_forecast_volume,
    get_retendering_forecast,
)


def _dias(offset: int) -> str:
    """Fecha ISO a `offset` días de hoy (negativo = pasado)."""
    return (datetime.now(UTC) + timedelta(days=offset)).strftime("%Y-%m-%d")


# ── get_forecast_volume ─────────────────────────────────────────────────────


def _rows_volumen() -> list[dict]:
    """5 meses de histórico (≥3 requerido por forecast_volume)."""
    rows = []
    for i, mes in enumerate(["2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]):
        for j in range(i + 1):  # volumen creciente: 1, 2, 3, 4, 5
            rows.append(
                {
                    "id_externo": f"L{mes}-{j}",
                    "titulo": "Servicio cloud",
                    "importe": 100_000.0,
                    "fecha_publicacion": f"{mes}-10",
                    "fecha_inicio": None,
                    "fecha_fin": None,
                    "duracion_valor": None,
                    "duracion_unidad": None,
                    "ccaa": "Madrid" if j % 2 == 0 else "Cataluña",
                    "tecnologia": "SAP",
                }
            )
    return rows


def test_forecast_volume_historico_mas_proyeccion():
    with (
        patch(
            "services.analytics.forecast_svc.load_stats_dataframe",
            return_value=_rows_volumen(),
        ),
        patch("services.analytics.forecast_svc.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_forecast_volume(ForecastFilters(months_ahead=3))

    # 5 meses de histórico + 3 de forecast
    assert len(result.series) == 8
    historico = [p for p in result.series if p.tipo == "histórico"]
    forecast = [p for p in result.series if p.tipo == "forecast"]
    assert len(historico) == 5
    assert len(forecast) == 3
    # Histórico: conteos mensuales 1..5, sin banda de confianza
    assert historico[0].mes == "2025-01"
    assert historico[0].valor == 1.0
    assert historico[4].valor == 5.0
    assert historico[0].lower is None
    # Forecast: meses consecutivos con banda lower/upper
    assert forecast[0].mes == "2025-06"
    assert forecast[0].lower is not None
    assert forecast[0].upper is not None
    assert forecast[0].valor >= 0.0


def test_forecast_volume_metric_sum():
    with (
        patch(
            "services.analytics.forecast_svc.load_stats_dataframe",
            return_value=_rows_volumen(),
        ),
        patch("services.analytics.forecast_svc.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_forecast_volume(ForecastFilters(months_ahead=2, metric="sum"))

    historico = [p for p in result.series if p.tipo == "histórico"]
    # Enero: 1 licitación x 100k
    assert historico[0].valor == 100_000.0


def test_forecast_volume_historico_insuficiente():
    """Con <3 meses de histórico el motor devuelve serie vacía."""
    rows = [r for r in _rows_volumen() if r["fecha_publicacion"].startswith("2025-01")]
    with (
        patch("services.analytics.forecast_svc.load_stats_dataframe", return_value=rows),
        patch("services.analytics.forecast_svc.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_forecast_volume(ForecastFilters())
    assert result.series == []


def test_forecast_volume_filtro_ccaa():
    with (
        patch(
            "services.analytics.forecast_svc.load_stats_dataframe",
            return_value=_rows_volumen(),
        ),
        patch("services.analytics.forecast_svc.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_forecast_volume(ForecastFilters(months_ahead=2, ccaa="Madrid"))

    historico = [p for p in result.series if p.tipo == "histórico"]
    # Enero tenía 1 fila (j=0, Madrid) → sigue 1; febrero 2 filas → 1 Madrid
    assert historico[0].valor == 1.0
    assert historico[1].valor == 1.0


def test_forecast_volume_dataset_vacio():
    with (
        patch("services.analytics.forecast_svc.load_stats_dataframe", return_value=[]),
        patch("services.analytics.forecast_svc.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_forecast_volume(ForecastFilters())
    assert result.series == []


# ── get_retendering_forecast ────────────────────────────────────────────────


def _rows_retendering() -> list[dict]:
    base = {
        "importe": 100_000.0,
        "fecha_inicio": None,
        "duracion_valor": None,
        "duracion_unidad": None,
        "ccaa": "Madrid",
        "tecnologia": "SAP",
    }
    return [
        # Mantenimiento que vence en ~60 días → bucket "<3 meses"
        {
            **base,
            "id_externo": "M1",
            "titulo": "Mantenimiento SAP ECC",
            "fecha_publicacion": _dias(-400),
            "fecha_fin": _dias(60),
        },
        # Soporte ya vencido → bucket "Ya vencido"
        {
            **base,
            "id_externo": "M2",
            "titulo": "Soporte de aplicaciones",
            "fecha_publicacion": _dias(-500),
            "fecha_fin": _dias(-30),
            "importe": 50_000.0,
        },
        # No es mantenimiento → excluido con solo_mantenimiento=True
        {
            **base,
            "id_externo": "X1",
            "titulo": "Desarrollo web corporativa",
            "fecha_publicacion": _dias(-100),
            "fecha_fin": _dias(30),
        },
        # Vence fuera del horizonte de 365 días → filtrado
        {
            **base,
            "id_externo": "M3",
            "titulo": "Mantenimiento CPD",
            "fecha_publicacion": _dias(-200),
            "fecha_fin": _dias(500),
        },
    ]


def _adj_retendering() -> list[dict]:
    return [
        {
            "licitacion_id": "M1",
            "fecha_adjudicacion": _dias(-380),
            "importe_adjudicado": 80_000.0,
            "n_ofertas_recibidas": 5,
            "nombre": "EMPRESA UNO",
        },
    ]


def test_retendering_buckets_y_horizonte():
    with (
        patch(
            "services.analytics.forecast_svc.load_stats_dataframe",
            return_value=_rows_retendering(),
        ),
        patch(
            "services.analytics.forecast_svc.load_raw_adjudicaciones",
            return_value=_adj_retendering(),
        ),
    ):
        result = get_retendering_forecast(RetenderingFilters(horizonte_dias=365))

    ids = {e.id_externo for e in result.forecast_entries}
    assert ids == {"M1", "M2"}  # X1 no es mantenimiento, M3 fuera de horizonte
    assert result.resumen.ya_vencido == 1
    assert result.resumen.menos_3m == 1
    assert result.resumen.mas_doce_m == 0


def test_retendering_enriquece_con_adjudicacion():
    with (
        patch(
            "services.analytics.forecast_svc.load_stats_dataframe",
            return_value=_rows_retendering(),
        ),
        patch(
            "services.analytics.forecast_svc.load_raw_adjudicaciones",
            return_value=_adj_retendering(),
        ),
    ):
        result = get_retendering_forecast(RetenderingFilters())

    m1 = next(e for e in result.forecast_entries if e.id_externo == "M1")
    assert m1.adjudicatarios == "EMPRESA UNO"
    assert m1.baja_pct == pytest.approx(20.0)  # (1 - 80k/100k) x 100
    assert m1.estado_forecast == "<3 meses"
    assert m1.dias_hasta_fin is not None
    assert 55 <= m1.dias_hasta_fin <= 61


def test_retendering_incluye_todos_los_tipos_sin_solo_mantenimiento():
    with (
        patch(
            "services.analytics.forecast_svc.load_stats_dataframe",
            return_value=_rows_retendering(),
        ),
        patch(
            "services.analytics.forecast_svc.load_raw_adjudicaciones",
            return_value=_adj_retendering(),
        ),
    ):
        result = get_retendering_forecast(RetenderingFilters(solo_mantenimiento=False))

    ids = {e.id_externo for e in result.forecast_entries}
    assert "X1" in ids


def test_retendering_dataset_vacio():
    with (
        patch("services.analytics.forecast_svc.load_stats_dataframe", return_value=[]),
        patch("services.analytics.forecast_svc.load_raw_adjudicaciones", return_value=[]),
    ):
        result = get_retendering_forecast(RetenderingFilters())
    assert result.forecast_entries == []
    assert result.resumen.ya_vencido == 0
