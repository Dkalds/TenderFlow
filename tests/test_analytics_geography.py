"""Tests para services/analytics/geography (by_ccaa + by_provincia).

Caracterización de la migración pandas -> SQL (ADR-023): siembran un dataset
sintético en el schema aislado (``tmp_db``) y comprueban los mismos valores
que daba la agregación pandas original.
"""

from __future__ import annotations

from services.analytics.geography import GeoFilters, get_geography


def _insert(rows: list[dict]) -> None:
    from db.upsert import Licitacion, upsert_licitaciones

    upsert_licitaciones(
        [
            Licitacion(
                id_externo=r["id_externo"],
                titulo=r.get("titulo", "Contrato TI"),
                ccaa=r.get("ccaa"),
                provincia=r.get("provincia"),
                importe=r.get("importe"),
                fecha_publicacion=r.get("fecha_publicacion", "2025-01-01T00:00:00+00:00"),
                tecnologia=r.get("tecnologia"),
            )
            for r in rows
        ]
    )


def _rows() -> list[dict]:
    return [
        {
            "id_externo": "L1",
            "ccaa": "Madrid",
            "provincia": "Madrid",
            "importe": 100.0,
            "fecha_publicacion": "2025-01-01T00:00:00+00:00",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L2",
            "ccaa": "Madrid",
            "provincia": "Madrid",
            "importe": 200.0,
            "fecha_publicacion": "2025-01-02T00:00:00+00:00",
            "tecnologia": "SAP",
        },
        {
            "id_externo": "L3",
            "ccaa": "Cataluña",
            "provincia": "Barcelona",
            "importe": 300.0,
            "fecha_publicacion": "2025-01-03T00:00:00+00:00",
            "tecnologia": "Cloud",
        },
        {
            "id_externo": "L4",
            "ccaa": "Cataluña",
            "provincia": None,  # provincia nula → excluida de by_provincia
            "importe": 50.0,
            "fecha_publicacion": "2025-01-04T00:00:00+00:00",
            "tecnologia": "Cloud",
        },
    ]


def test_geography_by_ccaa_counts_and_pct(tmp_db):
    _insert(_rows())

    res = get_geography(GeoFilters())

    by = {e.ccaa: e for e in res.by_ccaa}
    assert by["Madrid"].count == 2
    assert by["Cataluña"].count == 2
    assert by["Madrid"].importe == 300.0
    assert by["Cataluña"].importe == 350.0
    assert by["Madrid"].pct == 50.0
    assert res.concentracion_top3 == 100.0


def test_geography_by_provincia_aggregates_full_dataset(tmp_db):
    _insert(_rows())

    res = get_geography(GeoFilters())

    provs = {p.provincia: p for p in res.by_provincia}
    # Madrid: 2 licitaciones, 300; Barcelona: 1, 300; provincia nula excluida.
    assert provs["Madrid"].count == 2
    assert provs["Madrid"].importe == 300.0
    assert provs["Barcelona"].count == 1
    assert len(res.by_provincia) == 2


def test_geography_by_provincia_respects_filters(tmp_db):
    """La agregación de provincias respeta los filtros (no es un sample global)."""
    _insert(_rows())

    res = get_geography(GeoFilters(tecnologia="SAP"))

    # Solo las filas SAP (Madrid); Barcelona es Cloud y queda fuera.
    assert {p.provincia for p in res.by_provincia} == {"Madrid"}
    assert res.by_provincia[0].count == 2


def test_geography_empty_dataset(tmp_db):
    res = get_geography(GeoFilters())

    assert res.by_ccaa == []
    assert res.ccaa_mas_activa is None
