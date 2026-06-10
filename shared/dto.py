"""DTOs Pydantic v2 para la frontera FastAPI ↔ aplicación.

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


# ── Watchlist (F1) ──────────────────────────────────────────────────────────


class WatchlistEntry(BaseModel):
    """Entrada de la watchlist de un usuario.

    Contrato compartido entre `services/watchlist.py`, `api/routes/watchlist_feed.py`
    y las vistas de watchlist de la aplicación.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    user_id: str
    licitacion_id: str
    note: str | None = Field(default=None, max_length=2000)
    pinned: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WatchlistAlertDTO(BaseModel):
    """Alerta generada por scheduler/watchlist_alerts.py."""

    model_config = ConfigDict(from_attributes=True)

    user_id: str
    licitacion_id: str
    kind: str = Field(
        description="estado_cambio|fecha_proxima|importe_actualizado|nueva_adjudicacion"
    )
    payload: dict[str, str | int | float | None] = Field(default_factory=dict)
    created_at: datetime | None = None


# ── Clustering (F1) ─────────────────────────────────────────────────────────


class ClusterSummary(BaseModel):
    """Resumen de un cluster generado por `services/clusters.py`."""

    model_config = ConfigDict(from_attributes=True)

    cluster_id: int
    label: str | None = None
    size: int = Field(ge=0)
    centroid_terms: list[str] = Field(default_factory=list)
    representative_ids: list[str] = Field(default_factory=list)
    silhouette: float | None = None
    inertia: float | None = None
    computed_at: datetime | None = None


class ClusteringRunDTO(BaseModel):
    """Metadata de una ejecución de clustering, persistida en model_registry."""

    model_config = ConfigDict(from_attributes=True)

    run_id: str
    algorithm: str = "minibatch_kmeans"
    k: int = Field(ge=2)
    n_samples: int = Field(ge=0)
    dataset_hash: str
    model_artifact_uri: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    created_at: datetime | None = None
