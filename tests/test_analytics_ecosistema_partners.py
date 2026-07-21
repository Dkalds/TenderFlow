"""Tests para services/analytics/ecosistema_partners — grafo de co-licitación REAL.

Las aristas deben salir de UTEs conjuntas reales (parseadas del ``nombre``), no de
co-ocurrencia geográfica. Aserciones estructurales para no depender de la forma
exacta de ``normalize_company``.
"""

from __future__ import annotations

from unittest.mock import patch

from services.analytics.ecosistema_partners import (
    PartnerGraphFilters,
    get_partnership_graph,
)

_PATCH = "services.analytics.ecosistema_partners.load_raw_adjudicaciones"


def _rows() -> list[dict]:
    return [
        # UTE ALFA+BETA, 2 contratos (1000 + 2000)
        {
            "es_ute": 1,
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 1000.0,
        },
        {
            "es_ute": 1,
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 2000.0,
        },
        # UTE ALFA+GAMMA, 1 contrato
        {
            "es_ute": 1,
            "nombre": "UTE CONSTRUCCIONES ALFA - SERVICIOS GAMMA",
            "importe_adjudicado": 500.0,
        },
        # No-UTE: se ignora (no co-licitación)
        {"es_ute": 0, "nombre": "EMPRESA SOLA SL", "importe_adjudicado": 300.0},
    ]


def test_partnership_edges_are_real_utes():
    with patch(_PATCH, return_value=_rows()):
        res = get_partnership_graph(PartnerGraphFilters(min_contratos=1, top_nodes=20))

    # 2 parejas reales: (alfa,beta) y (alfa,gamma); 3 nodos.
    assert len(res.edges) == 2
    assert len(res.nodes) == 3
    assert res.total_utes == 3  # 3 adjudicaciones UTE (la no-UTE no cuenta)

    # La pareja con 2 contratos acumula importe 3000.
    strong = max(res.edges, key=lambda e: e.contratos)
    assert strong.contratos == 2
    assert strong.importe == 3000.0


def test_partnership_min_contratos_filters_edges():
    with patch(_PATCH, return_value=_rows()):
        res = get_partnership_graph(PartnerGraphFilters(min_contratos=2))

    # Solo la pareja con >= 2 co-licitaciones sobrevive.
    assert len(res.edges) == 1
    assert res.edges[0].contratos == 2


def test_partnership_empty_without_utes():
    rows = [{"es_ute": 0, "nombre": "EMPRESA SOLA SL", "importe_adjudicado": 100.0}]
    with patch(_PATCH, return_value=rows):
        res = get_partnership_graph(PartnerGraphFilters())
    assert res.edges == []
    assert res.nodes == []
    assert res.total_utes == 0


def _rows_two_clusters() -> list[dict]:
    # Dos UTEs desconectadas → dos comunidades.
    return [
        {
            "es_ute": 1,
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 5000.0,
        },
        {
            "es_ute": 1,
            "nombre": "UTE SERVICIOS DELTA - LIMPIEZA EPSILON",
            "importe_adjudicado": 1000.0,
        },
    ]


def test_partnership_communities_summary():
    with patch(_PATCH, return_value=_rows_two_clusters()):
        res = get_partnership_graph(PartnerGraphFilters(min_contratos=1, top_nodes=20))

    # Cada UTE desconectada forma su propia comunidad.
    assert len(res.communities) == 2
    # Cada resumen expone líder, tamaño y top miembros.
    for c in res.communities:
        assert c.size >= 1
        assert c.leader
        assert c.leader in c.top_members
    # Orden por importe total del clúster desc: el de 5000 va primero.
    assert res.communities[0].importe_total >= res.communities[1].importe_total
