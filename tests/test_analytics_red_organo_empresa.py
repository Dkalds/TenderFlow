"""Tests para services/analytics/red_organo_empresa — grafo de adjudicaciones REALES.

Caracterización de la migración pandas -> SQL (ADR-023): siembran
licitaciones + adjudicaciones reales en el schema aislado (``tmp_db``) — las
aristas llegan YA agregadas de ``AdjudicacionRepository.organ_company_edges``
— y afirman los mismos valores que daba el motor pandas. Las aristas deben
salir de la relación contractual real (órgano → empresa), no de co-ocurrencia
CCAA.
"""

from __future__ import annotations

import pytest

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

pytestmark = pytest.mark.usefixtures("tmp_db")


def _seed(rows: list[dict]) -> None:
    from db.upsert import (
        Adjudicacion,
        Licitacion,
        replace_adjudicaciones_batch,
        upsert_licitaciones,
    )

    lics = {}
    grouped: dict[str, list[Adjudicacion]] = {}
    for r in rows:
        lic_id = r["licitacion_id"]
        lics[lic_id] = Licitacion(
            id_externo=lic_id,
            titulo=r.get("titulo", f"Contrato {lic_id}"),
            organo_contratacion=r.get("organo_contratacion"),
            url=r.get("url"),
        )
        grouped.setdefault(lic_id, []).append(
            Adjudicacion(
                licitacion_id=lic_id,
                nombre=r["nombre"],
                importe_adjudicado=r.get("importe_adjudicado"),
                fecha_adjudicacion=r.get("fecha_adjudicacion"),
                ccaa=r.get("ccaa"),
            )
        )
    upsert_licitaciones(list(lics.values()))
    _total, _dropped, failed = replace_adjudicaciones_batch(grouped)
    assert failed == 0


def _rows() -> list[dict]:
    return [
        # Órgano A → EMPRESA UNO (2 contratos, 1000 + 2000)
        {
            "organo_contratacion": "Organo A",
            "nombre": "EMPRESA UNO SL",
            "importe_adjudicado": 1000.0,
            "fecha_adjudicacion": "2025-01-10",
            "licitacion_id": "LIC-1",
            "titulo": "Servicios de mantenimiento",
            "url": "https://example.org/lic-1",
        },
        {
            "organo_contratacion": "Organo A",
            "nombre": "EMPRESA UNO SL",
            "importe_adjudicado": 2000.0,
            "fecha_adjudicacion": "2025-02-10",
            "licitacion_id": "LIC-2",
            "titulo": "Obras de reforma",
            "url": "https://example.org/lic-2",
        },
        # Órgano A → EMPRESA DOS (1 contrato)
        {
            "organo_contratacion": "Organo A",
            "nombre": "EMPRESA DOS SA",
            "importe_adjudicado": 500.0,
            "fecha_adjudicacion": "2025-03-10",
            "licitacion_id": "LIC-3",
            "titulo": "Suministro de material",
            "url": "https://example.org/lic-3",
        },
        # Órgano B → EMPRESA UNO (1 contrato)
        {
            "organo_contratacion": "Organo B",
            "nombre": "EMPRESA UNO SL",
            "importe_adjudicado": 3000.0,
            "fecha_adjudicacion": "2025-01-20",
            "licitacion_id": "LIC-4",
            "titulo": "Consultoría",
            "url": "https://example.org/lic-4",
        },
    ]


def test_graph_edges_are_real_adjudications():
    _seed(_rows())
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
    _seed(_rows())
    res = get_organ_company_graph(GraphFilters(min_contratos=2))

    # Solo (Organo A, EMPRESA UNO SL) tiene >= 2 contratos.
    assert len(res.edges) == 1
    assert res.edges[0].contratos == 2
    assert res.edges[0].empresa == "EMPRESA UNO SL"


def test_graph_empty_when_no_rows():
    res = get_organ_company_graph(GraphFilters())
    assert res.nodes == []
    assert res.edges == []
    assert res.total_organos == 0


def test_graph_identity_prefers_master_canonico(tmp_db):
    """La identidad de empresa usa el maestro canónico y cae al nombre raw.

    Dos adjudicaciones con nombres raw distintos («Empresa Uno», «EMPRESA UNO,
    S.L.») enlazadas a la misma empresa canónica deben colapsar en un único
    nodo con el nombre del maestro — la regla que antes aplicaba pandas en
    ``_prepare_df`` y ahora vive en la expresión SQL del repositorio.
    """
    db_mod, _ = tmp_db
    _seed(
        [
            {
                "organo_contratacion": "Organo A",
                "nombre": "Empresa Uno",
                "importe_adjudicado": 1000.0,
                "fecha_adjudicacion": "2025-01-10",
                "licitacion_id": "LIC-M1",
            },
            {
                "organo_contratacion": "Organo A",
                "nombre": "EMPRESA UNO, S.L.",
                "importe_adjudicado": 2000.0,
                "fecha_adjudicacion": "2025-02-10",
                "licitacion_id": "LIC-M2",
            },
        ]
    )
    from db.empresas import create_empresa, link_adjudicacion

    with db_mod.connect() as conn:
        empresa_id = create_empresa(conn, nombre_canonico="EMPRESA UNO SL")
        ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM adjudicaciones WHERE licitacion_id IN (?, ?)",
                ("LIC-M1", "LIC-M2"),
            ).fetchall()
        ]
        for adj_id in ids:
            link_adjudicacion(conn, adj_id, empresa_id)

    res = get_organ_company_graph(GraphFilters())

    assert res.total_empresas == 1
    edge = next(e for e in res.edges if e.organo == "Organo A")
    assert edge.empresa == "EMPRESA UNO SL"
    assert edge.contratos == 2
    assert edge.importe_total == 3000.0


# ── Concentración por órgano ─────────────────────────────────────────────


def test_concentracion_por_organo():
    _seed(_rows())
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
    _seed(_rows())
    res = get_organ_company_ego(EgoFilters(entity_type="organo", entity_key="Organo A"))
    organos = {n.name for n in res.nodes if n.type == "organo"}
    empresas = {n.name for n in res.nodes if n.type == "empresa"}
    assert organos == {"Organo A"}
    assert empresas == {"EMPRESA UNO SL", "EMPRESA DOS SA"}
    # Ninguna arista de Organo B se cuela.
    assert all(e.organo == "Organo A" for e in res.edges)


def test_ego_empresa_devuelve_sus_organos():
    _seed(_rows())
    res = get_organ_company_ego(EgoFilters(entity_type="empresa", entity_key="EMPRESA UNO SL"))
    organos = {n.name for n in res.nodes if n.type == "organo"}
    empresas = {n.name for n in res.nodes if n.type == "empresa"}
    assert empresas == {"EMPRESA UNO SL"}
    assert organos == {"Organo A", "Organo B"}


# ── Drill-down de arista ─────────────────────────────────────────────────


def test_edge_detail_lista_licitaciones_reales():
    _seed(_rows())
    res = get_organ_company_edge(EdgeDetailFilters(organo="Organo A", empresa="EMPRESA UNO SL"))
    assert res.n_licitaciones == 2
    assert res.importe_total == 3000.0
    ids = {lic.licitacion_id for lic in res.licitaciones}
    assert ids == {"LIC-1", "LIC-2"}
    # Orden por importe desc: LIC-2 (2000) primero.
    assert res.licitaciones[0].licitacion_id == "LIC-2"
    assert res.licitaciones[0].url == "https://example.org/lic-2"
    assert res.licitaciones[0].fecha_adjudicacion == "2025-02-10"


def test_edge_detail_vacio_si_no_hay_relacion():
    _seed(_rows())
    res = get_organ_company_edge(EdgeDetailFilters(organo="Organo B", empresa="EMPRESA DOS SA"))
    assert res.n_licitaciones == 0
    assert res.licitaciones == []


def test_edge_detail_limit_no_recorta_totales():
    _seed(_rows())
    res = get_organ_company_edge(
        EdgeDetailFilters(organo="Organo A", empresa="EMPRESA UNO SL", limit=1)
    )
    assert len(res.licitaciones) == 1
    assert res.n_licitaciones == 2
    assert res.importe_total == 3000.0
