"""DTOs Pydantic v2 para la frontera FastAPI ↔ dashboard.

Define los modelos de datos para serialización/deserialización en la API.
Estos modelos son el contrato público del sistema.

Uso:
    from shared.dto import LicitacionSummary, AdjudicacionDetail
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LicitacionSummary(BaseModel):
    """Resumen de una licitación (listados, búsquedas)."""

    model_config = ConfigDict(from_attributes=True)

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = Field(default=None, ge=0)
    estado: str | None = None
    fecha_publicacion: datetime | None = None
    ccaa: str | None = None
    cpv: str | None = None
    url: str | None = None
    tecnologia: str | None = None


class LicitacionDetail(LicitacionSummary):
    """Detalle completo de una licitación."""

    descripcion: str | None = None
    tipo_contrato: str | None = None
    moneda: str | None = None
    provincia: str | None = None
    duracion_valor: float | None = None
    duracion_unidad: str | None = None
    fecha_limite: datetime | None = None
    fecha_inicio: datetime | None = None
    fecha_fin: datetime | None = None
    fecha_extraccion: datetime | None = None
    nuts_code: str | None = None


class AdjudicacionSummary(BaseModel):
    """Resumen de una adjudicación."""

    model_config = ConfigDict(from_attributes=True)

    licitacion_id: str
    nombre: str | None = None
    nif: str | None = None
    importe_adjudicado: float | None = Field(default=None, ge=0)
    fecha_adjudicacion: datetime | None = None
    ccaa: str | None = None


class KpiSnapshotDTO(BaseModel):
    """Snapshot de KPIs pre-computados."""

    model_config = ConfigDict(from_attributes=True)

    total_licitaciones: int = 0
    total_adjudicadas: int = 0
    importe_medio: float | None = None
    importe_total: float | None = None
    computed_at: datetime | None = None


class PaginatedResponse(BaseModel):
    """Respuesta paginada genérica."""

    items: list[LicitacionSummary]
    total: int
    limit: int
    offset: int


class SearchRequest(BaseModel):
    """Request de búsqueda del investigador."""

    question: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)
    only_filtered: bool = True
    allowed_ids: list[str] | None = None


class SearchResult(BaseModel):
    """Resultado de búsqueda con score."""

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    score: float = 0.0
    source: str = ""
