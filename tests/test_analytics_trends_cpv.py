"""Tests unitarios para services/analytics/trends_cpv.

Caracterización de la migración pandas -> SQL (ADR-023): siembran el dataset
sintético en el schema aislado (``tmp_db``).
"""

from __future__ import annotations

from datetime import date

from services.analytics.trends_cpv import TrendsCpvFilters, get_trends_cpv


def _insert(rows: list[dict]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=r["id_externo"],
                titulo=r.get("titulo", "Contrato TI"),
                cpv=r.get("cpv"),
                importe=r.get("importe"),
                fecha_publicacion=r.get("fecha_publicacion"),
                ccaa=r.get("ccaa"),
                tecnologia=r.get("tecnologia"),
            )
            for r in rows
        ]
    )


def _rows() -> list[dict]:
    return [
        {
            "id_externo": "L1",
            "cpv": "72000000",
            "importe": 100_000.0,
            "fecha_publicacion": "2025-01-10",
            "ccaa": "Madrid",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L2",
            "cpv": "72000000",
            "importe": 200_000.0,
            "fecha_publicacion": "2025-02-05",
            "ccaa": "Madrid",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L3",
            "cpv": "48000000",
            "importe": 50_000.0,
            "fecha_publicacion": "2025-01-15",
            "ccaa": "Cataluña",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L4",
            "cpv": None,  # sin CPV → fuera del análisis
            "importe": 999_000.0,
            "fecha_publicacion": "2025-01-20",
            "ccaa": "Madrid",
            "tecnologia": "SAP",
        },
    ]


def test_ranking_por_importe_y_summary(tmp_db):
    _insert(_rows())
    result = get_trends_cpv(TrendsCpvFilters())

    assert [r.cpv for r in result.top_cpv_by_importe] == ["72000000", "48000000"]
    top = result.top_cpv_by_importe[0]
    assert top.importe_total == 300_000.0
    assert top.count == 2

    assert result.summary.total_cpvs == 2
    assert result.summary.periodo_inicio == "2025-01"
    assert result.summary.periodo_fin == "2025-02"


def test_series_mensuales_por_cpv(tmp_db):
    _insert(_rows())
    result = get_trends_cpv(TrendsCpvFilters())

    series = {s.cpv: s.series for s in result.series_by_cpv}
    puntos_72 = {p.period: p for p in series["72000000"]}
    assert set(puntos_72) == {"2025-01", "2025-02"}
    assert puntos_72["2025-01"].count == 1
    assert puntos_72["2025-01"].importe == 100_000.0
    # Orden cronológico dentro de la serie
    assert [p.period for p in series["72000000"]] == ["2025-01", "2025-02"]


def test_top_n_limita_ranking_y_series(tmp_db):
    _insert(_rows())
    result = get_trends_cpv(TrendsCpvFilters(top_n=1))

    assert [r.cpv for r in result.top_cpv_by_importe] == ["72000000"]
    assert [s.cpv for s in result.series_by_cpv] == ["72000000"]
    # total_cpvs refleja el universo completo, no el top-N
    assert result.summary.total_cpvs == 2


def test_filtro_cpv_exacto(tmp_db):
    _insert(_rows())
    result = get_trends_cpv(TrendsCpvFilters(cpv="48000000"))

    assert [r.cpv for r in result.top_cpv_by_importe] == ["48000000"]
    assert result.summary.total_cpvs == 1


def test_filtro_fechas(tmp_db):
    _insert(_rows())
    result = get_trends_cpv(
        TrendsCpvFilters(fecha_desde=date(2025, 2, 1), fecha_hasta=date(2025, 2, 28))
    )

    # Solo L2 (feb) sobrevive
    assert [r.cpv for r in result.top_cpv_by_importe] == ["72000000"]
    assert result.top_cpv_by_importe[0].count == 1
    assert result.summary.periodo_inicio == "2025-02"


def test_dataset_vacio(tmp_db):
    result = get_trends_cpv(TrendsCpvFilters())
    assert result.series_by_cpv == []
    assert result.top_cpv_by_importe == []
    assert result.summary.total_cpvs == 0
