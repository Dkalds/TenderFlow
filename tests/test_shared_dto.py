"""Tests para shared/dto.py — DTOs Pydantic v2."""

from __future__ import annotations

import pytest


def test_licitacion_summary_instantiation():
    from shared.dto import LicitacionSummary

    dto = LicitacionSummary(id_externo="TEST-001", titulo="SAP ERP")
    assert dto.id_externo == "TEST-001"
    assert dto.titulo == "SAP ERP"


def test_licitacion_summary_optional_fields():
    from shared.dto import LicitacionSummary

    dto = LicitacionSummary(id_externo="X", titulo="T")
    assert dto.importe is None
    assert dto.ccaa is None
    assert dto.tecnologia is None


def test_licitacion_detail_extends_summary():
    from shared.dto import LicitacionDetail, LicitacionSummary

    assert issubclass(LicitacionDetail, LicitacionSummary)


def test_licitacion_detail_has_extra_fields():
    from shared.dto import LicitacionDetail

    dto = LicitacionDetail(id_externo="X", titulo="T", descripcion="Desc", url="https://x.com")
    assert dto.descripcion == "Desc"
    assert dto.url == "https://x.com"


def test_adjudicacion_summary():
    from shared.dto import AdjudicacionSummary

    dto = AdjudicacionSummary(licitacion_id="TEST-001", nombre="Empresa SA")
    assert dto.licitacion_id == "TEST-001"
    assert dto.nombre == "Empresa SA"


def test_paginated_response():
    from shared.dto import LicitacionSummary, PaginatedResponse

    items = [LicitacionSummary(id_externo=f"T-{i}", titulo=f"T{i}") for i in range(3)]
    resp = PaginatedResponse(items=items, total=10, limit=3, offset=0)
    assert resp.total == 10
    assert len(resp.items) == 3


def test_kpi_snapshot_dto():
    from shared.dto import KpiSnapshotDTO

    dto = KpiSnapshotDTO(total_licitaciones=42, importe_medio=150000.0)
    assert dto.total_licitaciones == 42
    assert dto.importe_medio == pytest.approx(150000.0)


def test_watchlist_entry():
    from shared.dto import WatchlistEntry

    entry = WatchlistEntry(user_id="user1", licitacion_id="TEST-001")
    assert entry.licitacion_id == "TEST-001"


def test_from_attributes_orm_compat():
    """from_attributes=True permite inicializar desde objetos con atributos."""
    from shared.dto import LicitacionSummary

    class FakeLic:
        id_externo = "ORM-001"
        titulo = "ORM Test"
        importe = 100.0
        ccaa = None
        tecnologia = None
        estado = None
        fecha_publicacion = None
        organo_contratacion = None
        cpv = None
        tipo_contrato = None

    dto = LicitacionSummary.model_validate(FakeLic(), from_attributes=True)
    assert dto.id_externo == "ORM-001"


def test_search_request():
    from shared.dto import SearchRequest

    req = SearchRequest(question="¿Qué licitaciones de SAP hay en Madrid?", top_k=5)
    assert req.top_k == 5


def test_cluster_summary():
    from shared.dto import ClusterSummary

    cs = ClusterSummary(cluster_id=0, size=10, centroid_terms=["SAP", "ERP", "implantación"])
    assert cs.cluster_id == 0
    assert len(cs.centroid_terms) == 3
