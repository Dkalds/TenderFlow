"""Tests de contrato para la frontera API ↔ dashboard.

Verifica que:
1. Los DTOs de shared/dto.py son serializables/deserializables correctamente.
2. Los campos obligatorios del contrato siguen presentes tras refactors.
3. La serialización JSON es estable (round-trip).
4. Los campos de fecha aceptan strings ISO 8601 y datetime objects.
5. Los campos de importe rechazan valores negativos.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# LicitacionSummary — contrato mínimo
# ---------------------------------------------------------------------------


def test_summary_required_field_id_externo():
    """id_externo es el campo identificador único, siempre debe estar."""
    import pydantic

    from shared.dto import LicitacionSummary

    with pytest.raises((pydantic.ValidationError, TypeError)):
        LicitacionSummary()  # sin id_externo


import pytest


def test_summary_json_round_trip():
    """Serializar a JSON y deserializar produce el mismo DTO."""
    from shared.dto import LicitacionSummary

    original = LicitacionSummary(
        id_externo="ES-2024-001",
        titulo="Licitación SAP S/4HANA",
        organo_contratacion="Ministerio de Hacienda",
        importe=150_000.0,
        estado="PUB",
        fecha_publicacion=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
        ccaa="MD",
        cpv="72267100",
        tecnologia="SAP",
    )
    serialized = original.model_dump_json()
    restored = LicitacionSummary.model_validate_json(serialized)
    assert restored.id_externo == original.id_externo
    assert restored.importe == original.importe
    assert restored.ccaa == original.ccaa


def test_summary_importe_negative_rejected():
    """El contrato rechaza importes negativos (ge=0)."""
    import pydantic

    from shared.dto import LicitacionSummary

    with pytest.raises(pydantic.ValidationError):
        LicitacionSummary(id_externo="X", titulo="T", importe=-100.0)


def test_summary_from_orm_attributes():
    """from_attributes=True permite crear DTOs desde objetos con atributos."""
    from shared.dto import LicitacionSummary

    class FakeOrm:
        id_externo = "ES-2024-001"
        titulo = "SAP"
        organo_contratacion = None
        importe = 50_000.0
        estado = "ADJ"
        fecha_publicacion = None
        ccaa = "CT"
        cpv = "48000000"
        url = None
        tecnologia = "SAP"

    dto = LicitacionSummary.model_validate(FakeOrm(), from_attributes=True)
    assert dto.id_externo == "ES-2024-001"
    assert dto.ccaa == "CT"


# ---------------------------------------------------------------------------
# LicitacionDetail — herencia y campos extra
# ---------------------------------------------------------------------------


def test_detail_inherits_all_summary_fields():
    """LicitacionDetail incluye todos los campos de LicitacionSummary."""
    from shared.dto import LicitacionDetail, LicitacionSummary

    summary_fields = set(LicitacionSummary.model_fields.keys())
    detail_fields = set(LicitacionDetail.model_fields.keys())
    assert summary_fields.issubset(detail_fields), (
        f"LicitacionDetail pierde campos de LicitacionSummary: {summary_fields - detail_fields}"
    )


def test_detail_extra_fields_present():
    """LicitacionDetail tiene campos adicionales sobre LicitacionSummary."""
    from shared.dto import LicitacionDetail, LicitacionSummary

    extra = set(LicitacionDetail.model_fields.keys()) - set(LicitacionSummary.model_fields.keys())
    assert "descripcion" in extra
    assert "tipo_contrato" in extra
    assert "fecha_extraccion" in extra


def test_detail_fecha_as_iso_string():
    """Los campos de fecha aceptan strings ISO 8601."""
    from shared.dto import LicitacionDetail

    dto = LicitacionDetail(
        id_externo="X",
        titulo="T",
        fecha_publicacion="2024-01-15T10:00:00Z",
        fecha_limite="2024-02-01T00:00:00+00:00",
    )
    assert dto.fecha_publicacion is not None
    assert isinstance(dto.fecha_publicacion, datetime)


# ---------------------------------------------------------------------------
# AdjudicacionSummary
# ---------------------------------------------------------------------------


def test_adjudicacion_importe_negative_rejected():
    """El contrato de adjudicaciones rechaza importes negativos."""
    import pydantic

    from shared.dto import AdjudicacionSummary

    with pytest.raises(pydantic.ValidationError):
        AdjudicacionSummary(licitacion_id="X", importe_adjudicado=-1.0)


def test_adjudicacion_json_round_trip():
    from shared.dto import AdjudicacionSummary

    original = AdjudicacionSummary(
        licitacion_id="ES-2024-001",
        nombre="Empresa SAP S.L.",
        nif="B12345678",
        importe_adjudicado=120_000.0,
        ccaa="MD",
    )
    restored = AdjudicacionSummary.model_validate_json(original.model_dump_json())
    assert restored.licitacion_id == original.licitacion_id
    assert restored.importe_adjudicado == original.importe_adjudicado


# ---------------------------------------------------------------------------
# PaginatedResponse
# ---------------------------------------------------------------------------


def test_paginated_response_structure():
    from shared.dto import LicitacionSummary, PaginatedResponse

    items = [LicitacionSummary(id_externo=f"ES-{i}", titulo=f"T{i}") for i in range(3)]
    resp = PaginatedResponse(items=items, total=100, limit=3, offset=0)
    assert len(resp.items) == 3
    assert resp.total == 100
    assert resp.limit == 3
    assert resp.offset == 0


def test_paginated_response_no_more():
    from shared.dto import LicitacionSummary, PaginatedResponse

    items = [LicitacionSummary(id_externo="ES-1", titulo="T1")]
    resp = PaginatedResponse(items=items, total=1, limit=10, offset=0)
    assert resp.total == 1


# ---------------------------------------------------------------------------
# KpiSnapshotDTO
# ---------------------------------------------------------------------------


def test_kpi_snapshot_defaults():
    from shared.dto import KpiSnapshotDTO

    kpi = KpiSnapshotDTO()
    assert kpi.total_licitaciones == 0
    assert kpi.total_adjudicadas == 0
    assert kpi.importe_medio is None


def test_kpi_snapshot_serialization():
    from shared.dto import KpiSnapshotDTO

    kpi = KpiSnapshotDTO(
        total_licitaciones=500,
        total_adjudicadas=200,
        importe_medio=75_000.0,
        importe_total=15_000_000.0,
        computed_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    data = json.loads(kpi.model_dump_json())
    assert data["total_licitaciones"] == 500
    assert data["importe_total"] == 15_000_000.0
