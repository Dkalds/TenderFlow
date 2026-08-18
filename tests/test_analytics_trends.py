"""Tests for the Trends analytics service (series mensual/semanal/diaria).

Caracterización de la migración pandas -> SQL (ADR-023): siembran el dataset
sintético en el schema aislado (``tmp_db``) y afirman los mismos valores que
daba la agregación pandas. Cubre el grouping por día que alimenta el heatmap
del Calendario: cada día debe ser su conteo REAL de publicaciones, no un
reparto sintético de la serie semanal (ADR-014, Patrón 1).
"""

from __future__ import annotations

import services.analytics.trends as tr_mod


def _insert(rows: list[dict]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=r["id_externo"],
                titulo=r.get("titulo", "Contrato TI"),
                importe=r.get("importe"),
                fecha_publicacion=r.get("fecha_publicacion"),
                ccaa=r.get("ccaa"),
                tecnologia=r.get("tecnologia"),
                estado=r.get("estado"),
            )
            for r in rows
        ]
    )


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


def test_trends_group_by_day_real_counts(tmp_db):
    """group_by=day agrega por fecha exacta (YYYY-MM-DD), sin reparto sintético."""
    _insert(_rows())
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


def test_trends_group_by_month_aggregates(tmp_db):
    """group_by=month colapsa los días en su mes (comportamiento por defecto)."""
    _insert(_rows())
    res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by="month"))

    by_period = {p.period: p for p in res.series}
    assert by_period["2026-03"].count == 3
    assert by_period["2026-04"].count == 1


def test_trends_group_by_week_labels(tmp_db):
    """group_by=week etiqueta como %Y-W%V del lunes de la semana (paridad pandas)."""
    _insert(_rows())
    res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by="week"))

    by_period = {p.period: p for p in res.series}
    # 2026-03-02 es lunes → semana ISO 10 de 2026; el 04 cae en la misma semana.
    assert by_period["2026-W10"].count == 3
    assert by_period["2026-W10"].importe == 350.0


def test_trends_heatmap_month_by_estado(tmp_db):
    _insert(_rows())
    res = tr_mod.get_trends(tr_mod.TrendsFilters())

    cells = {(c.row, c.col): c.value for c in res.heatmap}
    assert cells[("2026-03", "PUB")] == 2
    assert cells[("2026-03", "ADJ")] == 1
    assert cells[("2026-04", "PUB")] == 1


def test_trends_filters_apply_before_grouping(tmp_db):
    """Los filtros (ccaa/tecnologia) acotan antes de construir la serie diaria."""
    _insert(_rows())
    res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by="day", tecnologia="ORACLE"))
    assert {p.period for p in res.series} == {"2026-03-04"}
    assert sum(p.count for p in res.series) == 1


def test_trends_histogram_bins(tmp_db):
    _insert(_rows())
    res = tr_mod.get_trends(tr_mod.TrendsFilters())

    bins = {b.bin_label: b.count for b in res.histogram_bins}
    # 50 y 100 y 200 → bin 0-1K; 500 → 0-1K también. Todos < 1000.
    assert bins["0-1K"] == 4
    assert bins["1M-5M"] == 0


def test_trends_mes_pico(tmp_db):
    _insert(_rows())
    res = tr_mod.get_trends(tr_mod.TrendsFilters())

    assert res.mes_pico is not None
    assert res.mes_pico["mes"] == "2026-04"
    assert res.mes_pico["importe"] == 500.0
    assert res.mes_pico["count"] == 1


def test_trends_empty(tmp_db):
    res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by="day"))
    assert res.series == []
    assert res.histogram_bins == []
    assert res.mes_pico is None


def test_trends_declara_la_granularidad_usada(tmp_db):
    """La respuesta dice con qué roll-up construyó la serie.

    `period` cambia de formato con `group_by` (YYYY-MM / YYYY-Www / YYYY-MM-DD),
    así que el cliente necesita saberlo del propio payload y no de la URL que
    recuerde haber pedido. Campo aditivo: su default es el `month` de siempre.
    """
    _insert(_rows())
    for freq in ("month", "week", "day"):
        res = tr_mod.get_trends(tr_mod.TrendsFilters(group_by=freq))
        assert res.group_by == freq
        # Dataset de 4 filas: muy por debajo del techo, serie intacta.
        assert res.serie_truncada is False
        assert len(res.series) <= tr_mod.MAX_TREND_POINTS
