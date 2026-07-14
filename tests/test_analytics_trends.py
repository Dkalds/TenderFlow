"""Tests for the Trends analytics service (series mensual/semanal/diaria).

Cubre el grouping por día que alimenta el heatmap del Calendario: cada día
debe ser su conteo REAL de publicaciones, no un reparto sintético de la serie
semanal (ADR-014, Patrón 1). Data access mockeado en ``load_stats_dataframe``.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

import services.analytics.trends as tr_mod


def _rows() -> list[dict]:
    # Dos publicaciones el mismo día, una en otro día de la misma semana,
    # y una en un mes distinto → permite distinguir day/week/month.
    return [
        {
            "id_externo": "A",
            "fecha_publicacion": "2026-03-02T10:00:00+00:00",
            "importe": 100.0,
            "ccaa": "Madrid",
            "tecnologia": "SAP",
            "estado": "PUB",
        },
        {
            "id_externo": "B",
            "fecha_publicacion": "2026-03-02T18:00:00+00:00",
            "importe": 200.0,
            "ccaa": "Madrid",
            "tecnologia": "SAP",
            "estado": "PUB",
        },
        {
            "id_externo": "C",
            "fecha_publicacion": "2026-03-04T09:00:00+00:00",
            "importe": 50.0,
            "ccaa": "Cataluña",
            "tecnologia": "ORACLE",
            "estado": "ADJ",
        },
        {
            "id_externo": "D",
            "fecha_publicacion": "2026-04-10T09:00:00+00:00",
            "importe": 500.0,
            "ccaa": "Madrid",
            "tecnologia": "SAP",
            "estado": "PUB",
        },
    ]


def test_trends_group_by_day_real_counts():
    """group_by=day agrega por fecha exacta (YYYY-MM-DD), sin reparto sintético."""
    with patch.object(tr_mod, "load_stats_base_df", return_value=pd.DataFrame(_rows())):
        res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by="day"))

    by_period = {p.period: p for p in res.series}
    # Cada period es un día concreto.
    assert all(len(p) == 10 and p[4] == "-" and p[7] == "-" for p in by_period)
    # Dos publicaciones el 2026-03-02 → conteo real 2 (no repartido).
    assert by_period["2026-03-02"].count == 2
    assert by_period["2026-03-02"].importe == 300.0
    assert by_period["2026-03-04"].count == 1
    assert by_period["2026-04-10"].count == 1
    # La suma de conteos diarios == total de filas.
    assert sum(p.count for p in res.series) == 4


def test_trends_group_by_month_aggregates():
    """group_by=month colapsa los días en su mes (comportamiento por defecto)."""
    with patch.object(tr_mod, "load_stats_base_df", return_value=pd.DataFrame(_rows())):
        res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by="month"))

    by_period = {p.period: p for p in res.series}
    assert by_period["2026-03"].count == 3
    assert by_period["2026-04"].count == 1


def test_trends_filters_apply_before_grouping():
    """Los filtros (ccaa/tecnologia) acotan antes de construir la serie diaria."""
    with patch.object(tr_mod, "load_stats_base_df", return_value=pd.DataFrame(_rows())):
        res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by="day", tecnologia="ORACLE"))
    assert {p.period for p in res.series} == {"2026-03-04"}
    assert sum(p.count for p in res.series) == 1


def test_trends_empty():
    with patch.object(tr_mod, "load_stats_base_df", return_value=pd.DataFrame([])):
        res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by="day"))
    assert res.series == []
