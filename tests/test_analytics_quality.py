"""Tests for the Data Quality analytics service.

Cubre los dos arreglos de integridad del panel de Calidad de Datos:

- **DLQ real**: ``dlq_count`` consulta ``failed_extractions`` en vez del stub que
  devolvía siempre 0 (el panel veía 0 pérdidas aunque hubiera fallos).
- **Formato de fecha** (no completitud): una fecha presente pero ``DD/MM/YYYY``
  cuenta como completa, pero NO como ISO → ``pct_fecha_iso``/``fechas_no_iso``.

Data access mockeado en ``load_stats_dataframe``; la DLQ se mockea en su origen.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

import services.analytics.quality as q_mod


def _rows() -> list[dict]:
    return [
        {
            "id_externo": "A",
            "titulo": "x",
            "fecha_publicacion": "2026-03-01T00:00:00+00:00",  # ISO con hora
            "importe": 1.0,
            "cpv": "72000000",
            "estado": "PUB",
            "ccaa": "Madrid",
        },
        {
            "id_externo": "B",
            "titulo": "y",
            "fecha_publicacion": "2026-03-02",  # ISO fecha
            "importe": 2.0,
            "cpv": "72000000",
            "estado": "PUB",
            "ccaa": "Madrid",
        },
        {
            "id_externo": "C",
            "titulo": "z",
            "fecha_publicacion": "31/12/2025",  # legacy DD/MM/YYYY → no-ISO
            "importe": 3.0,
            "cpv": "72000000",
            "estado": "PUB",
            "ccaa": "Madrid",
        },
        {
            "id_externo": "D",
            "titulo": "w",
            "fecha_publicacion": None,  # nulo → fuera del denominador de formato
            "importe": 4.0,
            "cpv": "72000000",
            "estado": "PUB",
            "ccaa": "Madrid",
        },
    ]


def test_quality_date_format_vs_completeness():
    """pct_fecha (completitud) y pct_fecha_iso (formato) son métricas distintas."""
    with (
        patch.object(q_mod, "load_stats_base_df", return_value=pd.DataFrame(_rows())),
        patch("db.dlq.count_unresolved", return_value=0),
    ):
        res = q_mod.get_quality()

    # Completitud: 3 de 4 no nulas = 75%.
    assert round(res.pct_fecha, 1) == 75.0
    # Formato: de las 3 presentes, 2 son ISO = 66.7%; 1 es no-ISO (la DD/MM/YYYY).
    assert round(res.pct_fecha_iso, 1) == 66.7
    assert res.fechas_no_iso == 1


def test_quality_dlq_count_is_real_not_stub():
    """dlq_count refleja la DLQ real (antes era un stub fijo en 0)."""
    with (
        patch.object(q_mod, "load_stats_base_df", return_value=pd.DataFrame(_rows())),
        patch("db.dlq.count_unresolved", return_value=7),
    ):
        res = q_mod.get_quality()
    assert res.dlq_count == 7


def test_quality_dlq_count_on_empty_dataset():
    """Sin registros analíticos, el conteo de DLQ sigue siendo real."""
    with (
        patch.object(q_mod, "load_stats_base_df", return_value=pd.DataFrame([])),
        patch("db.dlq.count_unresolved", return_value=3),
    ):
        res = q_mod.get_quality()
    assert res.total_records == 0
    assert res.dlq_count == 3


def test_quality_dlq_count_best_effort_on_error():
    """Si la DLQ no está disponible, dlq_count cae a 0 sin romper el panel."""
    with (
        patch.object(q_mod, "load_stats_base_df", return_value=pd.DataFrame(_rows())),
        patch("db.dlq.count_unresolved", side_effect=RuntimeError("no table")),
    ):
        res = q_mod.get_quality()
    assert res.dlq_count == 0
    # El resto de métricas se calcula igualmente.
    assert res.total_records == 4


def test_quality_all_iso_dates():
    rows = [
        {"id_externo": "A", "fecha_publicacion": "2026-01-01", "importe": 1.0},
        {"id_externo": "B", "fecha_publicacion": "2026-01-02T10:00:00+00:00", "importe": 2.0},
    ]
    with (
        patch.object(q_mod, "load_stats_base_df", return_value=pd.DataFrame(rows)),
        patch("db.dlq.count_unresolved", return_value=0),
    ):
        res = q_mod.get_quality()
    assert res.pct_fecha_iso == 100.0
    assert res.fechas_no_iso == 0
