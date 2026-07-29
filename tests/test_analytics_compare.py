"""Tests unitarios para services/analytics/compare.

Parchea load_stats_dataframe con filas sintéticas (patrón de
test_analytics_organos.py); sin BD.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd

from services.analytics.compare import CompareFilters, _pct_delta, get_compare_periods


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


def _typed(df: pd.DataFrame) -> pd.DataFrame:
    """Simula la conversión canónica que ahora aplica ``load_stats_base_df()``
    (ver ``services/licitaciones.py::_build``): el fixture de este módulo usa
    fechas ISO en crudo, así que el mock debe entregarlas ya convertidas para
    reflejar el contrato real."""
    if df.empty:
        return df
    for col in ("fecha_publicacion", "fecha_limite", "fecha_inicio", "fecha_fin"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
    if "importe" in df.columns:
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    return df


def _filters(**overrides) -> CompareFilters:
    base = {
        "range_a_desde": date(2025, 1, 1),
        "range_a_hasta": date(2025, 1, 31),
        "range_b_desde": date(2025, 2, 1),
        "range_b_hasta": date(2025, 2, 28),
    }
    base.update(overrides)
    return CompareFilters(**base)


def test_compare_periodos_y_deltas():
    with patch(
        "services.analytics.compare.load_stats_base_df", return_value=_typed(pd.DataFrame(_rows()))
    ):
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


def test_compare_filtro_ccaa():
    with patch(
        "services.analytics.compare.load_stats_base_df", return_value=_typed(pd.DataFrame(_rows()))
    ):
        result = get_compare_periods(_filters(ccaa="Madrid"))

    # Solo L1 (enero, Madrid) y L3 (febrero, Madrid)
    assert result.period_a.total == 1
    assert result.period_a.importe_total == 100_000.0
    assert result.period_b.total == 1


def test_compare_periodo_a_vacio_no_divide_por_cero():
    """Con período A sin datos los deltas quedan en 0.0 (no ZeroDivisionError)."""
    with patch(
        "services.analytics.compare.load_stats_base_df", return_value=_typed(pd.DataFrame(_rows()))
    ):
        result = get_compare_periods(
            _filters(range_a_desde=date(2020, 1, 1), range_a_hasta=date(2020, 1, 31))
        )

    assert result.period_a.total == 0
    assert result.period_b.total == 1
    assert result.deltas.total_pct == 0.0
    assert result.deltas.importe_total_pct == 0.0


def test_compare_dataset_vacio():
    with patch("services.analytics.compare.load_stats_base_df", return_value=pd.DataFrame([])):
        result = get_compare_periods(_filters())
    assert result.period_a.total == 0
    assert result.period_b.total == 0
    assert result.deltas.total_pct == 0.0


def test_pct_delta_negativo_con_base_negativa():
    """La base negativa usa abs() para que el signo del delta sea el del cambio."""
    assert _pct_delta(-100.0, -50.0) == 50.0
    assert _pct_delta(0.0, 10.0) == 0.0
