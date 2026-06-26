"""Tests para services/analytics/red_organo_empresa — grafo de adjudicaciones REALES.

Mockean ``load_raw_adjudicaciones`` con adjudicaciones sintéticas; las aristas deben
salir de la relación contractual real (órgano → empresa), no de co-ocurrencia CCAA.
"""

from __future__ import annotations

from unittest.mock import patch

from services.analytics.red_organo_empresa import GraphFilters, get_organ_company_graph

_PATCH = "services.analytics.red_organo_empresa.load_raw_adjudicaciones"


def _rows() -> list[dict]:
    return [
        # Órgano A → EMPRESA UNO (2 contratos, 1000 + 2000)
        {
            "organo_contratacion": "Organo A",
            "empresa_nombre_master": "EMPRESA UNO SL",
            "nombre": "Empresa Uno",
            "importe_adjudicado": 1000.0,
            "fecha_adjudicacion": "2025-01-10",
        },
        {
            "organo_contratacion": "Organo A",
            "empresa_nombre_master": "EMPRESA UNO SL",
            "nombre": "Empresa Uno",
            "importe_adjudicado": 2000.0,
            "fecha_adjudicacion": "2025-02-10",
        },
        # Órgano A → EMPRESA DOS (1 contrato)
        {
            "organo_contratacion": "Organo A",
            "empresa_nombre_master": "EMPRESA DOS SA",
            "nombre": "Empresa Dos",
            "importe_adjudicado": 500.0,
            "fecha_adjudicacion": "2025-03-10",
        },
        # Órgano B → EMPRESA UNO (1 contrato)
        {
            "organo_contratacion": "Organo B",
            "empresa_nombre_master": "EMPRESA UNO SL",
            "nombre": "Empresa Uno",
            "importe_adjudicado": 3000.0,
            "fecha_adjudicacion": "2025-01-20",
        },
    ]


def test_graph_edges_are_real_adjudications():
    with patch(_PATCH, return_value=_rows()):
        res = get_organ_company_graph(GraphFilters(top_organos=10, top_empresas=10))

    # La arista (Organo A, EMPRESA UNO SL) refleja 2 contratos reales, importe 3000.
    edge = next(e for e in res.edges if e.organo == "Organo A" and e.empresa == "EMPRESA UNO SL")
    assert edge.contratos == 2
    assert edge.importe_total == 3000.0

    # Totales sobre el dataset completo (distinct).
    assert res.total_organos == 2
    assert res.total_empresas == 2

    organos = {n.name for n in res.nodes if n.type == "organo"}
    empresas = {n.name for n in res.nodes if n.type == "empresa"}
    assert organos == {"Organo A", "Organo B"}
    assert empresas == {"EMPRESA UNO SL", "EMPRESA DOS SA"}


def test_graph_min_contratos_filters_edges():
    with patch(_PATCH, return_value=_rows()):
        res = get_organ_company_graph(GraphFilters(min_contratos=2))

    # Solo (Organo A, EMPRESA UNO SL) tiene >= 2 contratos.
    assert len(res.edges) == 1
    assert res.edges[0].contratos == 2
    assert res.edges[0].empresa == "EMPRESA UNO SL"


def test_graph_empty_when_no_rows():
    with patch(_PATCH, return_value=[]):
        res = get_organ_company_graph(GraphFilters())
    assert res.nodes == []
    assert res.edges == []
    assert res.total_organos == 0
