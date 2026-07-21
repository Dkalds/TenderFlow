"""Tests para services/analytics/red_organo_empresa — grafo de adjudicaciones REALES.

Mockean ``load_raw_adjudicaciones`` con adjudicaciones sintéticas; las aristas deben
salir de la relación contractual real (órgano → empresa), no de co-ocurrencia CCAA.
"""

from __future__ import annotations

from unittest.mock import patch

from services.analytics.red_organo_empresa import (
    ConcentracionFilters,
    EdgeDetailFilters,
    EgoFilters,
    GraphFilters,
    get_organ_company_edge,
    get_organ_company_ego,
    get_organ_company_graph,
    get_organ_concentration,
)

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
            "licitacion_id": "LIC-1",
            "titulo": "Servicios de mantenimiento",
            "url_lic": "https://example.org/lic-1",
        },
        {
            "organo_contratacion": "Organo A",
            "empresa_nombre_master": "EMPRESA UNO SL",
            "nombre": "Empresa Uno",
            "importe_adjudicado": 2000.0,
            "fecha_adjudicacion": "2025-02-10",
            "licitacion_id": "LIC-2",
            "titulo": "Obras de reforma",
            "url_lic": "https://example.org/lic-2",
        },
        # Órgano A → EMPRESA DOS (1 contrato)
        {
            "organo_contratacion": "Organo A",
            "empresa_nombre_master": "EMPRESA DOS SA",
            "nombre": "Empresa Dos",
            "importe_adjudicado": 500.0,
            "fecha_adjudicacion": "2025-03-10",
            "licitacion_id": "LIC-3",
            "titulo": "Suministro de material",
            "url_lic": "https://example.org/lic-3",
        },
        # Órgano B → EMPRESA UNO (1 contrato)
        {
            "organo_contratacion": "Organo B",
            "empresa_nombre_master": "EMPRESA UNO SL",
            "nombre": "Empresa Uno",
            "importe_adjudicado": 3000.0,
            "fecha_adjudicacion": "2025-01-20",
            "licitacion_id": "LIC-4",
            "titulo": "Consultoría",
            "url_lic": "https://example.org/lic-4",
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


# ── Concentración por órgano ─────────────────────────────────────────────


def test_concentracion_por_organo():
    with patch(_PATCH, return_value=_rows()):
        res = get_organ_concentration(ConcentracionFilters(min_contratos=1))

    organo_a = next(o for o in res.organos if o.organo == "Organo A")
    # Organo A: EMPRESA UNO 3000 (85.7%) + EMPRESA DOS 500 (14.3%) → HHI ≈ 7551.
    assert organo_a.n_empresas == 2
    assert organo_a.n_contratos == 3
    assert organo_a.top_empresa == "EMPRESA UNO SL"
    assert organo_a.cuota_top1 == 85.7  # 3000 / 3500
    assert organo_a.apertura == "Cerrado"
    assert res.total_organos == 2


# ── Ego-network ──────────────────────────────────────────────────────────


def test_ego_organo_devuelve_solo_su_vecindario():
    with patch(_PATCH, return_value=_rows()):
        res = get_organ_company_ego(EgoFilters(entity_type="organo", entity_key="Organo A"))
    organos = {n.name for n in res.nodes if n.type == "organo"}
    empresas = {n.name for n in res.nodes if n.type == "empresa"}
    assert organos == {"Organo A"}
    assert empresas == {"EMPRESA UNO SL", "EMPRESA DOS SA"}
    # Ninguna arista de Organo B se cuela.
    assert all(e.organo == "Organo A" for e in res.edges)


def test_ego_empresa_devuelve_sus_organos():
    with patch(_PATCH, return_value=_rows()):
        res = get_organ_company_ego(EgoFilters(entity_type="empresa", entity_key="EMPRESA UNO SL"))
    organos = {n.name for n in res.nodes if n.type == "organo"}
    empresas = {n.name for n in res.nodes if n.type == "empresa"}
    assert empresas == {"EMPRESA UNO SL"}
    assert organos == {"Organo A", "Organo B"}


# ── Drill-down de arista ─────────────────────────────────────────────────


def test_edge_detail_lista_licitaciones_reales():
    with patch(_PATCH, return_value=_rows()):
        res = get_organ_company_edge(EdgeDetailFilters(organo="Organo A", empresa="EMPRESA UNO SL"))
    assert res.n_licitaciones == 2
    assert res.importe_total == 3000.0
    ids = {lic.licitacion_id for lic in res.licitaciones}
    assert ids == {"LIC-1", "LIC-2"}
    # Orden por importe desc: LIC-2 (2000) primero.
    assert res.licitaciones[0].licitacion_id == "LIC-2"
    assert res.licitaciones[0].url == "https://example.org/lic-2"


def test_edge_detail_vacio_si_no_hay_relacion():
    with patch(_PATCH, return_value=_rows()):
        res = get_organ_company_edge(EdgeDetailFilters(organo="Organo B", empresa="EMPRESA DOS SA"))
    assert res.n_licitaciones == 0
    assert res.licitaciones == []
