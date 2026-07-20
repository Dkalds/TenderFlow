"""Tests unitarios para services/analytics/competitors.get_competitors.

Parchean ``load_raw_adjudicaciones`` con filas sintéticas (el mismo shape que
``load_raw_with_licitaciones``) para validar, sin tocar la BD:

* agrupación por empresa canónica del maestro v35 (no por string crudo),
* % de oferta única / sin competencia calculados con ``n_ofertas_recibidas``,
* filtros tecnologia / estado / importe_min / fecha,
* ``empresa_id`` y los totales (``total_empresas`` / ``importe_total``).
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from services.analytics.competitors import CompetitorFilters, get_competitors

_PATCH_TARGET = "services.analytics.competitors.load_raw_adjudicaciones"


def _rows() -> list[dict]:
    """Filas sintéticas: 3 empresas canónicas, una sin cobertura de ofertas."""
    return [
        # Accenture — dos variantes de nombre crudo, mismo maestro (empresa_id 10).
        {
            "licitacion_id": "L1",
            "nombre": "ACCENTURE S.L.",
            "nif": "A1",
            "empresa_id": 10,
            "empresa_nombre_master": "Accenture",
            "empresa_nif_master": "A-CANON",
            "ccaa": "Madrid",
            "importe_adjudicado": 80000.0,
            "importe_licitacion": 100000.0,
            "n_ofertas_recibidas": 1,
            "fecha_adjudicacion": "2025-06-01",
            "organo_contratacion": "Min X",
            "tecnologia": "SAP",
            "estado": "adjudicada",
            "es_pyme": 0,
        },
        {
            "licitacion_id": "L2",
            "nombre": "Accenture SLU",
            "nif": "A1",
            "empresa_id": 10,
            "empresa_nombre_master": "Accenture",
            "empresa_nif_master": "A-CANON",
            "ccaa": "Madrid",
            "importe_adjudicado": 90000.0,
            "importe_licitacion": 100000.0,
            "n_ofertas_recibidas": 3,
            "fecha_adjudicacion": "2025-07-01",
            "organo_contratacion": "Min Y",
            "tecnologia": "SAP",
            "estado": "adjudicada",
            "es_pyme": 0,
        },
        # Salesforce — empresa_id 20.
        {
            "licitacion_id": "L3",
            "nombre": "Salesforce Iberia",
            "nif": "B1",
            "empresa_id": 20,
            "empresa_nombre_master": "Salesforce",
            "empresa_nif_master": "B-CANON",
            "ccaa": "Cataluña",
            "importe_adjudicado": 50000.0,
            "importe_licitacion": 60000.0,
            "n_ofertas_recibidas": 1,
            "fecha_adjudicacion": "2025-05-01",
            "organo_contratacion": "Gen Cat",
            "tecnologia": "SALESFORCE",
            "estado": "adjudicada",
            "es_pyme": 1,
        },
        # Oracle — sin n_ofertas (cobertura nula), estado/fecha distintos para filtros.
        {
            "licitacion_id": "L4",
            "nombre": "Oracle Ibérica",
            "nif": "C1",
            "empresa_id": 30,
            "empresa_nombre_master": "Oracle",
            "empresa_nif_master": "C-CANON",
            "ccaa": "Madrid",
            "importe_adjudicado": 40000.0,
            "importe_licitacion": 70000.0,
            "n_ofertas_recibidas": None,
            "fecha_adjudicacion": "2025-04-01",
            "organo_contratacion": "Min Z",
            "tecnologia": "ORACLE",
            "estado": "anulada",
            "es_pyme": 0,
        },
    ]


def test_canonical_grouping_nif_and_empresa_id():
    with patch(_PATCH_TARGET, return_value=_rows()):
        res = get_competitors(CompetitorFilters())
    names = sorted(c.nombre for c in res.competitors)
    # Dos variantes de Accenture colapsan en una sola empresa canónica.
    assert names == ["Accenture", "Oracle", "Salesforce"]
    acc = next(c for c in res.competitors if c.nombre == "Accenture")
    assert acc.count == 2
    assert acc.empresa_id == 10
    assert acc.nif == "A-CANON"  # NIF canónico del maestro, no "A1"


def test_single_bid_metrics_use_n_ofertas():
    with patch(_PATCH_TARGET, return_value=_rows()):
        res = get_competitors(CompetitorFilters())
    # Global: L1,L2,L3 reportan ofertas; L1 y L3 son oferta única → 2/3.
    assert abs(res.pct_oferta_unica - (2 / 3 * 100)) < 0.01
    acc = next(c for c in res.competitors if c.nombre == "Accenture")
    # Accenture: 2 licitaciones con dato, 1 sin rival (L1) → 50%.
    assert acc.pct_monopolio == 50.0
    oracle = next(c for c in res.competitors if c.nombre == "Oracle")
    # Oracle no tiene cobertura de ofertas → desconocido (None), no 0.
    assert oracle.pct_monopolio is None


def test_totals_and_aux_blocks():
    with patch(_PATCH_TARGET, return_value=_rows()):
        res = get_competitors(CompetitorFilters())
    assert res.total_empresas == 3
    assert abs(res.importe_total - 260000.0) < 1
    assert res.total_adjudicaciones == 4
    # Bloques auxiliares poblados.
    assert {h.empresa for h in res.heatmap_ccaa}  # heatmap por CCAA
    assert {s.nombre for s in res.scatter_data}
    assert {e.mes for e in res.estacionalidad} == {4, 5, 6, 7}


def test_filter_tecnologia():
    with patch(_PATCH_TARGET, return_value=_rows()):
        res = get_competitors(CompetitorFilters(tecnologia="SAP"))
    assert [c.nombre for c in res.competitors] == ["Accenture"]
    assert res.total_empresas == 1


def test_filter_estado_and_importe_min():
    with patch(_PATCH_TARGET, return_value=_rows()):
        res_estado = get_competitors(CompetitorFilters(estado="adjudicada"))
        res_imp = get_competitors(CompetitorFilters(importe_min=100000))
    # estado=adjudicada excluye Oracle (anulada).
    assert "Oracle" not in {c.nombre for c in res_estado.competitors}
    # importe_min=100000 deja solo las licitaciones de Accenture (lic 100000).
    assert {c.nombre for c in res_imp.competitors} == {"Accenture"}


def test_filter_fecha_desde():
    with patch(_PATCH_TARGET, return_value=_rows()):
        res = get_competitors(CompetitorFilters(fecha_desde=date(2025, 6, 1)))
    # Solo L1 (06-01) y L2 (07-01) → Accenture.
    assert {c.nombre for c in res.competitors} == {"Accenture"}


def test_filter_fecha_hasta():
    with patch(_PATCH_TARGET, return_value=_rows()):
        res = get_competitors(CompetitorFilters(fecha_hasta=date(2025, 5, 31)))
    # Hasta 2025-05-31 → L3 (05-01) y L4 (04-01) → Salesforce y Oracle.
    assert {c.nombre for c in res.competitors} == {"Salesforce", "Oracle"}


def test_grouping_without_master_falls_back_to_raw_name():
    # Sin maestro (empresa_nombre_master ausente) cae al nombre crudo.
    rows = [
        {
            "licitacion_id": "L9",
            "nombre": "Indra Sistemas",
            "ccaa": "Madrid",
            "importe_adjudicado": 30000.0,
            "importe_licitacion": 40000.0,
            "n_ofertas_recibidas": 2,
            "fecha_adjudicacion": "2025-03-01",
            "organo_contratacion": "Min W",
            "tecnologia": "SAP",
            "estado": "adjudicada",
        }
    ]
    with patch(_PATCH_TARGET, return_value=rows):
        res = get_competitors(CompetitorFilters())
    assert [c.nombre for c in res.competitors] == ["Indra Sistemas"]
    assert res.competitors[0].empresa_id is None


def test_grouping_without_master_joins_distinct_names_with_same_nif():
    rows = [
        {
            "licitacion_id": "L-NIF-1",
            "nombre": "INDRA SISTEMAS, S.A.",
            "nif": "A-28599033",
            "importe_adjudicado": 30000.0,
            "importe_licitacion": 40000.0,
            "fecha_adjudicacion": "2025-03-01",
        },
        {
            "licitacion_id": "L-NIF-2",
            "nombre": "MINSAIT BUSINESS CONSULTING, S.L.",
            "nif": "A28599033",
            "importe_adjudicado": 50000.0,
            "importe_licitacion": 60000.0,
            "fecha_adjudicacion": "2025-04-01",
        },
    ]

    with patch(_PATCH_TARGET, return_value=rows):
        result = get_competitors(CompetitorFilters())

    assert result.total_empresas == 1
    competitor = result.competitors[0]
    assert competitor.count == 2
    assert competitor.importe == 80000.0
    assert competitor.nif == "A28599033"
    assert competitor.nifs == ["A28599033"]
    assert competitor.empresa_ids == []
    assert set(competitor.nombres_variantes) == {
        "INDRA SISTEMAS, S.A.",
        "MINSAIT BUSINESS CONSULTING, S.L.",
    }
    assert competitor.es_agrupacion is True


def test_grouping_joins_same_normalized_name_with_distinct_nifs_safely():
    rows = [
        {
            "licitacion_id": "L-NAME-1",
            "nombre": "ACME, S.L.",
            "nif": "B-11111111",
            "empresa_id": 40,
            "empresa_nombre_master": "Acme, S.L.",
            "empresa_nif_master": "B11111111",
            "importe_adjudicado": 20000.0,
            "importe_licitacion": 25000.0,
            "fecha_adjudicacion": "2025-03-01",
        },
        {
            "licitacion_id": "L-NAME-2",
            "nombre": "ACME SA",
            "nif": "A-22222222",
            "empresa_id": 41,
            "empresa_nombre_master": "ACME SA",
            "empresa_nif_master": "A22222222",
            "importe_adjudicado": 30000.0,
            "importe_licitacion": 40000.0,
            "fecha_adjudicacion": "2025-04-01",
        },
    ]

    with patch(_PATCH_TARGET, return_value=rows):
        result = get_competitors(CompetitorFilters())

    assert result.total_empresas == 1
    competitor = result.competitors[0]
    assert competitor.count == 2
    assert competitor.empresa_id is None
    assert competitor.empresa_ids == [40, 41]
    assert competitor.nif is None
    assert competitor.nifs == ["A22222222", "B11111111"]
    assert competitor.es_agrupacion is True


def test_grouping_does_not_join_distinct_names_through_placeholder_nif():
    rows = [
        {
            "licitacion_id": "L-EMPTY-NIF-1",
            "nombre": "Empresa Norte, S.L.",
            "nif": "N/A",
            "importe_adjudicado": 10000.0,
        },
        {
            "licitacion_id": "L-EMPTY-NIF-2",
            "nombre": "Empresa Sur, S.L.",
            "nif": "N/A",
            "importe_adjudicado": 20000.0,
        },
    ]

    with patch(_PATCH_TARGET, return_value=rows):
        result = get_competitors(CompetitorFilters())

    assert result.total_empresas == 2
    assert {competitor.nombre for competitor in result.competitors} == {
        "Empresa Norte, S.L.",
        "Empresa Sur, S.L.",
    }
    assert all(competitor.nifs == [] for competitor in result.competitors)


def test_empty_rows():
    with patch(_PATCH_TARGET, return_value=[]):
        res = get_competitors(CompetitorFilters())
    assert res.competitors == []
    assert res.total_empresas == 0
    assert res.total_adjudicaciones == 0


def test_contratos_por_anio_usa_los_anios_activos_de_cada_empresa():
    rows = _rows()
    rows[-1] = {**rows[-1], "fecha_adjudicacion": "2024-04-01"}

    with patch(_PATCH_TARGET, return_value=rows):
        result = get_competitors(CompetitorFilters())

    accenture = next(item for item in result.competitors if item.nombre == "Accenture")
    assert accenture.count == 2
    assert accenture.contratos_por_anio == 2
