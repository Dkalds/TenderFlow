"""Tests para services/analytics/ecosistema_partners — grafo de co-licitación REAL.

Caracterización de la migración pandas -> SQL (ADR-023): siembran
licitaciones + adjudicaciones reales en el schema aislado (``tmp_db``) — las
filas UTE llegan de la proyección acotada
``AdjudicacionRepository.load_ute_rows`` (patrón ``\\y``-delimitado en SQL).
Antes estos tests mockeaban el loader con una columna ``es_ute`` que el
camino real nunca producía (el endpoint llegaba siempre vacío en producción —
reparado por la migración). Las aristas deben salir de UTEs conjuntas reales
(parseadas del ``nombre``), no de co-ocurrencia geográfica. Aserciones
estructurales para no depender de la forma exacta de ``normalize_company``.
"""

from __future__ import annotations

import pytest

from services.analytics.ecosistema_partners import (
    PartnerGraphFilters,
    get_partnership_graph,
)

pytestmark = pytest.mark.usefixtures("tmp_db")


def _seed(rows: list[dict]) -> None:
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    lics = []
    grouped: dict[str, list[Adjudicacion]] = {}
    for i, r in enumerate(rows):
        lic_id = f"ECO-LIC-{i}"
        lics.append(Licitacion(id_externo=lic_id, titulo=f"Contrato {lic_id}"))
        grouped.setdefault(lic_id, []).append(
            Adjudicacion(
                licitacion_id=lic_id,
                nombre=r["nombre"],
                importe_adjudicado=r.get("importe_adjudicado"),
                ccaa=r.get("ccaa"),
            )
        )
    upsert_licitaciones(lics)
    _total, _dropped, failed = replace_adjudicaciones_batch(grouped)
    assert failed == 0


def _rows() -> list[dict]:
    return [
        # UTE ALFA+BETA, 2 contratos (1000 + 2000)
        {
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 1000.0,
        },
        {
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 2000.0,
        },
        # UTE ALFA+GAMMA, 1 contrato
        {
            "nombre": "UTE CONSTRUCCIONES ALFA - SERVICIOS GAMMA",
            "importe_adjudicado": 500.0,
        },
        # No-UTE: se ignora (no co-licitación)
        {"nombre": "EMPRESA SOLA SL", "importe_adjudicado": 300.0},
    ]


def test_partnership_edges_are_real_utes():
    _seed(_rows())
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
    _seed(_rows())
    res = get_partnership_graph(PartnerGraphFilters(min_contratos=2))

    # Solo la pareja con >= 2 co-licitaciones sobrevive.
    assert len(res.edges) == 1
    assert res.edges[0].contratos == 2


def test_partnership_empty_without_utes():
    _seed([{"nombre": "EMPRESA SOLA SL", "importe_adjudicado": 100.0}])
    res = get_partnership_graph(PartnerGraphFilters())
    assert res.edges == []
    assert res.nodes == []
    assert res.total_utes == 0


def test_partnership_word_boundary_no_matchea_substrings():
    """El patrón ``\\y``-delimitado no confunde substrings («COMPUTER» ∋ UTE)."""
    _seed(
        [
            {"nombre": "COMPUTER SERVICES SL", "importe_adjudicado": 100.0},
            {"nombre": "U.T.E. ALFA - BETA", "importe_adjudicado": 200.0},
        ]
    )
    res = get_partnership_graph(PartnerGraphFilters())
    # Solo la U.T.E. real cuenta (con puntos, como la deriva el enriquecimiento).
    assert res.total_utes == 1


def test_partnership_filtro_ccaa_en_sql():
    rows = _rows()
    rows[0]["ccaa"] = "Madrid"
    rows[1]["ccaa"] = "Cataluña"
    rows[2]["ccaa"] = "Madrid"
    _seed(rows)
    res = get_partnership_graph(PartnerGraphFilters(ccaa="Madrid", min_contratos=1))

    # Solo las 2 UTE de Madrid entran (1 alfa-beta + 1 alfa-gamma).
    assert res.total_utes == 2
    assert all(e.contratos == 1 for e in res.edges)


def _rows_two_clusters() -> list[dict]:
    # Dos UTEs desconectadas → dos comunidades.
    return [
        {
            "nombre": "UTE CONSTRUCCIONES ALFA - OBRAS BETA",
            "importe_adjudicado": 5000.0,
        },
        {
            "nombre": "UTE SERVICIOS DELTA - LIMPIEZA EPSILON",
            "importe_adjudicado": 1000.0,
        },
    ]


def test_partnership_communities_summary():
    _seed(_rows_two_clusters())
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
