"""Tests para services/analytics/utes — socios frecuentes de co-licitación (UTE)."""

from __future__ import annotations

from unittest.mock import patch

from services.analytics.utes import UTEFilters, get_utes

_PATCH = "services.analytics.utes.load_raw_adjudicaciones"


def _rows() -> list[dict]:
    return [
        {
            "es_ute": 1,
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 1000.0,
            "fecha_adjudicacion": "2025-01-10",
        },
        {
            "es_ute": 1,
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 2000.0,
            "fecha_adjudicacion": "2025-02-10",
        },
        {
            "es_ute": 0,
            "nombre": "EMPRESA SOLA SL",
            "importe_adjudicado": 300.0,
            "fecha_adjudicacion": "2025-01-15",
        },
    ]


def test_utes_socios_frecuentes_from_real_utes():
    with patch(_PATCH, return_value=_rows()):
        res = get_utes(UTEFilters())

    # Un par real (alfa, beta) co-licitando en 2 UTEs por importe 3000.
    assert len(res.socios_frecuentes) == 1
    par = res.socios_frecuentes[0]
    assert par.contratos == 2
    assert par.importe == 3000.0
    # KPIs: 2 adjudicaciones UTE (la individual no cuenta).
    assert res.kpis.total_ute == 2


def test_utes_no_socios_without_utes():
    rows = [
        {
            "es_ute": 0,
            "nombre": "EMPRESA SOLA SL",
            "importe_adjudicado": 100.0,
            "fecha_adjudicacion": "2025-01-10",
        }
    ]
    with patch(_PATCH, return_value=rows):
        res = get_utes(UTEFilters())
    assert res.socios_frecuentes == []
