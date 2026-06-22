"""Tests para services/analytics/geography (by_ccaa + by_provincia).

Mockean ``load_stats_dataframe`` con filas sintéticas para validar las
agregaciones sin tocar la BD.
"""

from __future__ import annotations

from unittest.mock import patch

from services.analytics.geography import GeoFilters, get_geography


def _rows() -> list[dict]:
    return [
        {
            "id_externo": "L1",
            "ccaa": "Madrid",
            "provincia": "Madrid",
            "importe": 100.0,
            "fecha_publicacion": "2025-01-01",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L2",
            "ccaa": "Madrid",
            "provincia": "Madrid",
            "importe": 200.0,
            "fecha_publicacion": "2025-01-02",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L3",
            "ccaa": "Cataluña",
            "provincia": "Barcelona",
            "importe": 300.0,
            "fecha_publicacion": "2025-01-03",
            "tecnologia": "Cloud",
        },
        {
            "id_externo": "L4",
            "ccaa": "Cataluña",
            "provincia": None,  # provincia nula → excluida
            "importe": 50.0,
            "fecha_publicacion": "2025-01-04",
            "tecnologia": "Cloud",
        },
    ]


def test_geography_by_provincia_aggregates_full_dataset():
    with patch(
        "services.analytics.geography.load_stats_dataframe", return_value=_rows()
    ):
        res = get_geography(GeoFilters())

    provs = {p.provincia: p for p in res.by_provincia}
    # Madrid: 2 licitaciones, 300; Barcelona: 1, 300; provincia nula excluida.
    assert provs["Madrid"].count == 2
    assert provs["Madrid"].importe == 300.0
    assert provs["Barcelona"].count == 1
    assert len(res.by_provincia) == 2


def test_geography_by_provincia_respects_filters():
    """La agregación de provincias respeta los filtros (no es un sample global)."""
    with patch(
        "services.analytics.geography.load_stats_dataframe", return_value=_rows()
    ):
        res = get_geography(GeoFilters(tecnologia="SAP"))

    # Solo las filas SAP (Madrid); Barcelona es Cloud y queda fuera.
    assert {p.provincia for p in res.by_provincia} == {"Madrid"}
    assert res.by_provincia[0].count == 2
