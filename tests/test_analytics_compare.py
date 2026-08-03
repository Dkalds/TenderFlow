"""Tests unitarios para services/analytics/compare.

Caracterización de la migración pandas -> SQL (ADR-023): siembran el dataset
sintético en el schema aislado (``tmp_db``) y afirman los mismos valores que
daba la agregación pandas.
"""

from __future__ import annotations

from datetime import date

from services.analytics.compare import CompareFilters, _pct_delta, get_compare_periods


def _insert(rows: list[dict]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=r["id_externo"],
                titulo=r.get("titulo", "Contrato TI"),
                organo_contratacion=r.get("organo_contratacion"),
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
            "organo_contratacion": "ORG A",
            "importe": 100_000.0,
            "fecha_publicacion": "2025-01-10",
            "ccaa": "Madrid",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L2",
            "organo_contratacion": "ORG B",
            "importe": 200_000.0,
            "fecha_publicacion": "2025-01-20",
            "ccaa": "Cataluña",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L3",
            "organo_contratacion": "ORG A",
            "importe": 150_000.0,
            "fecha_publicacion": "2025-02-15",
            "ccaa": "Madrid",
            "tecnologia": "SAP",
        },
    ]


def _filters(**overrides) -> CompareFilters:
    base = {
        "range_a_desde": date(2025, 1, 1),
        "range_a_hasta": date(2025, 1, 31),
        "range_b_desde": date(2025, 2, 1),
        "range_b_hasta": date(2025, 2, 28),
    }
    base.update(overrides)
    return CompareFilters(**base)


def test_compare_periodos_y_deltas(tmp_db):
    _insert(_rows())

    result = get_compare_periods(_filters())

    # Período A: L1 + L2 (enero)
    assert result.period_a.total == 2
    assert result.period_a.importe_total == 300_000.0
    assert result.period_a.importe_medio == 150_000.0
    assert result.period_a.organos == 2
    # Período B: L3 (febrero)
    assert result.period_b.total == 1
    assert result.period_b.importe_total == 150_000.0
    # Deltas B vs A
    assert result.deltas.total_pct == -50.0
    assert result.deltas.importe_total_pct == -50.0
    assert result.deltas.importe_medio_pct == 0.0
    assert result.deltas.organos_pct == -50.0


def test_compare_filtro_ccaa(tmp_db):
    _insert(_rows())

    result = get_compare_periods(_filters(ccaa="Madrid"))

    # Solo L1 (enero, Madrid) y L3 (febrero, Madrid)
    assert result.period_a.total == 1
    assert result.period_a.importe_total == 100_000.0
    assert result.period_b.total == 1


def test_compare_periodo_a_vacio_no_divide_por_cero(tmp_db):
    """Con período A sin datos los deltas quedan en 0.0 (no ZeroDivisionError)."""
    _insert(_rows())

    result = get_compare_periods(
        _filters(range_a_desde=date(2020, 1, 1), range_a_hasta=date(2020, 1, 31))
    )

    assert result.period_a.total == 0
    assert result.period_b.total == 1
    assert result.deltas.total_pct == 0.0
    assert result.deltas.importe_total_pct == 0.0


def test_compare_dataset_vacio(tmp_db):
    result = get_compare_periods(_filters())
    assert result.period_a.total == 0
    assert result.period_b.total == 0
    assert result.deltas.total_pct == 0.0


def test_pct_delta_negativo_con_base_negativa():
    """La base negativa usa abs() para que el signo del delta sea el del cambio."""
    assert _pct_delta(-100.0, -50.0) == 50.0
    assert _pct_delta(0.0, 10.0) == 0.0
