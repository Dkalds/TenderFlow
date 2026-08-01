"""DTOs Pydantic v2 para la frontera FastAPI ↔ aplicación.

Define los modelos de datos para serialización/deserialización en la API.
Estos modelos son el contrato público del sistema.

Uso:
    from shared.dto import LicitacionSummary, AdjudicacionDetail
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

# Postgres serializa timestamptz a texto sin los minutos del offset cuando son
# cero (p.ej. "2026-08-01 00:45:48.33444+00"), formato que el parser RFC3339
# estricto de pydantic rechaza con `datetime_from_date_parsing`. Todas las
# columnas de fecha llegan como TEXT desde repositories/*.py (ADR-016/021), así
# que cualquier `datetime` de este módulo puede recibir ese formato.
_PG_SHORT_TZ_OFFSET_RE = re.compile(
    r"^(?P<body>.*\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?P<offset>[+-]\d{2})$"
)


def _normalize_pg_datetime(value: Any) -> Any:
    """Completa el offset corto de Postgres (``+00`` → ``+00:00``) antes de parsear."""
    if isinstance(value, str):
        match = _PG_SHORT_TZ_OFFSET_RE.match(value)
        if match:
            return f"{match.group('body')}{match.group('offset')}:00"
    return value


PgDateTime = Annotated[datetime, BeforeValidator(_normalize_pg_datetime)]


class LicitacionSummary(BaseModel):
    """Resumen de una licitación (listados, búsquedas)."""

    model_config = ConfigDict(from_attributes=True)

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = Field(default=None, ge=0)
    estado: str | None = None
    fecha_publicacion: PgDateTime | None = None
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
    fecha_limite: PgDateTime | None = None
    fecha_inicio: PgDateTime | None = None
    fecha_fin: PgDateTime | None = None
    fecha_extraccion: PgDateTime | None = None
    nuts_code: str | None = None


class AdjudicacionSummary(BaseModel):
    """Resumen de una adjudicación."""

    model_config = ConfigDict(from_attributes=True)

    licitacion_id: str
    nombre: str | None = None
    nif: str | None = None
    importe_adjudicado: float | None = Field(default=None, ge=0)
    fecha_adjudicacion: PgDateTime | None = None
    ccaa: str | None = None


class KpiSnapshotDTO(BaseModel):
    """Snapshot de KPIs pre-computados."""

    model_config = ConfigDict(from_attributes=True)

    total_licitaciones: int = 0
    total_adjudicadas: int = 0
    importe_medio: float | None = None
    importe_total: float | None = None
    computed_at: PgDateTime | None = None


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
    created_at: PgDateTime | None = None
    updated_at: PgDateTime | None = None


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
    computed_at: PgDateTime | None = None


# Competitive company dossier


class CompetitiveCompanyIdentityDTO(BaseModel):
    """Canonical identity displayed in a competitor dossier."""

    empresa_id: int = Field(ge=1)
    nombre: str
    nif: str | None = None
    es_ute: bool = False
    grupo: str | None = None


class CompetitiveCompanyTotalsDTO(BaseModel):
    """Headline activity and data-coverage metrics for the selected scope."""

    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)
    importe_mediano: float | None = Field(default=None, ge=0)
    ofertas_medias: float | None = Field(default=None, ge=0)
    baja_media_pct: float | None = None
    pct_oferta_unica: float | None = Field(default=None, ge=0, le=100)
    cobertura_ofertas_pct: float = Field(default=0, ge=0, le=100)
    primera_adjudicacion: str | None = None
    ultima_adjudicacion: str | None = None
    organos: int = Field(default=0, ge=0)
    territorios: int = Field(default=0, ge=0)
    familias_cpv: int = Field(default=0, ge=0)


class CompetitiveCompanyBreakdownDTO(BaseModel):
    """Reusable amount/count distribution row (CPV, territory or buyer)."""

    codigo: str | None = None
    label: str
    cpv2: str | None = None
    ccaa: str | None = None
    organo: str | None = None
    contratos: int = Field(ge=0)
    importe: float = Field(ge=0)
    cuota_empresa_pct: float = Field(default=0, ge=0, le=100)
    ultima_adjudicacion: str | None = None


class CompetitiveCompanyYearDTO(BaseModel):
    """Annual activity point."""

    anio: int = Field(ge=1900, le=2200)
    contratos: int = Field(ge=0)
    importe: float = Field(ge=0)


class CompetitiveCompanyPositionDTO(BaseModel):
    """Market position inside the currently selected segment."""

    rank: int | None = Field(default=None, ge=1)
    empresas: int = Field(default=0, ge=0)
    cuota_pct: float | None = Field(default=None, ge=0, le=100)
    importe_segmento: float = Field(default=0, ge=0)


class CompetitiveCompanyComparisonDTO(BaseModel):
    """Current period compared with the immediately preceding equal period."""

    desde: str
    hasta: str
    anterior_desde: str
    anterior_hasta: str
    contratos: int = Field(default=0, ge=0)
    contratos_anterior: int = Field(default=0, ge=0)
    variacion_contratos_pct: float | None = None
    importe: float = Field(default=0, ge=0)
    importe_anterior: float = Field(default=0, ge=0)
    variacion_importe_pct: float | None = None
    importe_mediano: float | None = Field(default=None, ge=0)
    importe_mediano_anterior: float | None = Field(default=None, ge=0)


class CompetitiveCompanyConcentrationDTO(BaseModel):
    """Dependence on the most relevant public buyers."""

    organo_principal: str | None = None
    top1_contratos_pct: float = Field(default=0, ge=0, le=100)
    top1_importe_pct: float = Field(default=0, ge=0, le=100)
    top3_importe_pct: float = Field(default=0, ge=0, le=100)


class CompetitiveCompanySignalDTO(BaseModel):
    """Explainable movement or risk derived from observed awards."""

    kind: str
    tone: str = Field(pattern="^(positive|neutral|warning|negative)$")
    title: str
    detail: str


class CompetitiveCompanyScopeDTO(BaseModel):
    """Effective filters used to calculate a company dossier."""

    fecha_desde: str | None = None
    fecha_hasta: str | None = None
    cpv: str | None = None
    ccaas: list[str] = Field(default_factory=list)
    tecnologias: list[str] = Field(default_factory=list)
    importe_min: float | None = Field(default=None, ge=0)


class CompetitiveCompanyHistoryDTO(BaseModel):
    """Unfiltered company history, separate from the active analysis scope."""

    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)
    primera_adjudicacion: str | None = None
    ultima_adjudicacion: str | None = None


class CompetitiveCompanyAwardDTO(BaseModel):
    """Award row in the paginated company history."""

    licitacion_id: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    fecha_adjudicacion: str | None = None
    cpv: str | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    presupuesto_licitacion: float | None = Field(default=None, ge=0)
    importe_adjudicado: float | None = Field(default=None, ge=0)
    baja_pct: float | None = None
    n_ofertas_recibidas: int | None = Field(default=None, ge=0)
    expediente_url: str | None = None


class CompetitiveCompanyUteParticipationDTO(BaseModel):
    """UTE en la que la empresa participa como miembro, con su actividad propia.

    Deliberadamente separado de ``totales``/``posicion_mercado``, que solo
    cuentan lo adjudicado directamente a ``empresa_id`` -- sumarlo ahí
    duplicaría el importe ya atribuido a la UTE como entidad propia en
    cuota_mercado()/concentracion_hhi(). Esto es visibilidad adicional, no
    una redefinición de la cuota de mercado.
    """

    ute_empresa_id: int = Field(ge=1)
    ute_nombre: str
    otros_miembros: list[str] = Field(default_factory=list)
    contratos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)


class CompetitiveCompanyProfileDTO(BaseModel):
    """Full competitor dossier used by quick and deep company views."""

    empresa: CompetitiveCompanyIdentityDTO
    scope: CompetitiveCompanyScopeDTO
    actividad_historica: CompetitiveCompanyHistoryDTO
    totales: CompetitiveCompanyTotalsDTO
    posicion_mercado: CompetitiveCompanyPositionDTO
    comparacion: CompetitiveCompanyComparisonDTO
    concentracion_clientes: CompetitiveCompanyConcentrationDTO
    por_cpv: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    por_ccaa: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    organos_principales: list[CompetitiveCompanyBreakdownDTO] = Field(default_factory=list)
    por_anio: list[CompetitiveCompanyYearDTO] = Field(default_factory=list)
    movimientos: list[CompetitiveCompanySignalDTO] = Field(default_factory=list)
    contratos_recientes: list[CompetitiveCompanyAwardDTO] = Field(default_factory=list)
    participaciones_ute: list[CompetitiveCompanyUteParticipationDTO] = Field(default_factory=list)


class CompetitiveCompanyAwardsDTO(BaseModel):
    """Paginated award history for a canonical company."""

    items: list[CompetitiveCompanyAwardDTO] = Field(default_factory=list)
    total: int = Field(default=0, ge=0)
    limit: int = Field(ge=1, le=500)
    offset: int = Field(default=0, ge=0)


# ── Organizaciones y pursuits (Fase 1 TenderFlow) ──────────────────────────

OrganizationRole = Literal["owner", "admin", "member", "viewer"]
OrganizationMembershipStatus = Literal["active", "invited", "suspended", "revoked"]
PursuitStatus = Literal[
    "identified",
    "qualifying",
    "go_no_go",
    "preparing",
    "submitted",
    "won",
    "lost",
    "withdrawn",
]
PursuitDecision = Literal["pending", "go", "no_go"]
PursuitOutcome = Literal["pending", "won", "lost", "cancelled"]


class OrganizationSummary(BaseModel):
    """Organización de trabajo visible para el usuario autenticado."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=200)
    is_personal: bool
    role: OrganizationRole
    created_at: PgDateTime


class OrganizationMembershipOut(BaseModel):
    """Membresía sin datos de autenticación ni credenciales."""

    model_config = ConfigDict(extra="forbid")

    organization_id: int = Field(ge=1)
    user_id: int = Field(ge=1)
    role: OrganizationRole
    status: OrganizationMembershipStatus
    created_at: PgDateTime
    updated_at: PgDateTime


class OrganizationCreate(BaseModel):
    """Alta de un espacio compartido."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)


class OrganizationMembershipUpsert(BaseModel):
    """Alta o cambio de rol/estado de un miembro existente."""

    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(ge=1)
    role: OrganizationRole = "member"
    status: OrganizationMembershipStatus = "active"


class PursuitCreate(BaseModel):
    """Convierte una licitación existente en oportunidad colaborativa."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    licitacion_id: str = Field(min_length=1, max_length=500)
    organization_id: int | None = Field(default=None, ge=1)
    responsible_user_id: int | None = Field(default=None, ge=1)


class PursuitUpdate(BaseModel):
    """Patch parcial de una oportunidad con control optimista opcional."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    status: PursuitStatus | None = None
    decision: PursuitDecision | None = None
    decision_reason: str | None = Field(default=None, max_length=4000)
    responsible_user_id: int | None = Field(default=None, ge=1)
    offer_price_eur: float | None = Field(default=None, ge=0)
    outcome: PursuitOutcome | None = None
    awarded_amount_eur: float | None = Field(default=None, ge=0)
    outcome_reason: str | None = Field(default=None, max_length=4000)
    expected_version: int | None = Field(default=None, ge=1)


class PursuitEventOut(BaseModel):
    """Entrada inmutable del historial de una oportunidad."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    pursuit_id: int = Field(ge=1)
    event_type: str
    actor_user_id: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: PgDateTime


class PursuitSummary(BaseModel):
    """Oportunidad enriquecida con los datos básicos de su licitación."""

    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1)
    organization_id: int = Field(ge=1)
    licitacion_id: str
    tender_title: str | None = None
    tender_deadline: PgDateTime | None = None
    responsible_user_id: int | None = None
    responsible_name: str | None = None
    status: PursuitStatus
    decision: PursuitDecision
    decision_reason: str | None = None
    offer_price_eur: float | None = Field(default=None, ge=0)
    outcome: PursuitOutcome
    awarded_amount_eur: float | None = Field(default=None, ge=0)
    outcome_reason: str | None = None
    identified_at: PgDateTime
    decision_at: PgDateTime | None = None
    submitted_at: PgDateTime | None = None
    closed_at: PgDateTime | None = None
    created_at: PgDateTime
    updated_at: PgDateTime
    version: int = Field(ge=1)


class PursuitDetail(PursuitSummary):
    """Detalle de una oportunidad con su ledger append-only."""

    events: list[PursuitEventOut] = Field(default_factory=list)


class PursuitListResponse(BaseModel):
    """Listado paginado dentro de una única organización."""

    organization_id: int = Field(ge=1)
    items: list[PursuitSummary] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)
    offset: int = Field(ge=0)


class PursuitMetrics(BaseModel):
    """Métricas reproducibles de funnel y resultado por organización/periodo."""

    organization_id: int = Field(ge=1)
    period_from: PgDateTime | None = None
    period_to: PgDateTime | None = None
    pursuits_identified: int = Field(ge=0)
    pursuits_submitted: int = Field(ge=0)
    pursuits_won: int = Field(ge=0)
    pursuits_lost: int = Field(ge=0)
    win_rate: float | None = Field(default=None, ge=0, le=1)
    awarded_amount_eur: float = Field(default=0, ge=0)
    median_decision_time_hours: float | None = Field(default=None, ge=0)
