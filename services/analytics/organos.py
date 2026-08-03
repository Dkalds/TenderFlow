"""Organos analytics — ranking of contracting bodies.

Agrega en Postgres vía :class:`AggregateRepository` (ADR-023); hasta 2026-08
cargaba la tabla completa a pandas en el proceso API — bloqueado en Render por
el cortacircuitos full-table, que dejaba este endpoint vacío en producción.
La búsqueda ``q`` sigue siendo accent/case-insensitive: el servicio pliega la
aguja con ``fold_text`` y el repositorio pliega la columna en SQL.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.normalization import fold_text

log = get_logger(__name__)

_repo = AggregateRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OrganosFilters(BaseModel):
    """Query filters for organos endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    q: str | None = None
    limit: int = 50


class OrganoEntry(BaseModel):
    """Single organo ranking entry."""

    organo_contratacion: str
    count: int
    importe: float
    pct: float
    ccaa: str | None = None


class TreemapItem(BaseModel):
    """Single cell in the organo → tipo_contrato treemap breakdown."""

    organo: str
    tipo_contrato: str
    importe: float


class OrganosResult(BaseModel):
    """Combined organos response."""

    organos: list[OrganoEntry] = Field(default_factory=list)
    total_organos: int = 0
    importe_total: float = 0.0
    concentracion_top10: float = 0.0
    treemap_breakdown: list[TreemapItem] = Field(default_factory=list)


def _to_repo_filters(filters: OrganosFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_organos(filters: OrganosFilters) -> OrganosResult:
    """Compute organo ranking with concentration metrics."""
    log.info("analytics_organos_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)
    q_folded = fold_text(filters.q) if filters.q else None

    total, total_organos, importe_total = _repo.organos_totales(repo_filters, q_folded=q_folded)
    if total == 0:
        log.info("analytics_organos_done", total=0)
        return OrganosResult()

    # El ranking se pide con al menos 10 filas: la concentración top-10 se
    # calcula sobre él aunque el caller pida un limit menor.
    ranking = _repo.organos_ranking(
        repo_filters, q_folded=q_folded, limit=max(filters.limit, 10)
    )

    concentracion_top10 = (
        sum(int(r["count"]) for r in ranking[:10]) / total * 100 if total else 0.0
    )

    organos = [
        OrganoEntry(
            organo_contratacion=str(r["organo_contratacion"]),
            count=int(r["count"]),
            importe=float(r["importe"] or 0),
            pct=round(int(r["count"]) / total * 100, 2),
            ccaa=r.get("ccaa_mode"),
        )
        for r in ranking[: filters.limit]
    ]

    treemap_breakdown = [
        TreemapItem(
            organo=str(r["organo"]),
            tipo_contrato=str(r["tipo_contrato"]),
            importe=float(r["importe"]),
        )
        for r in _repo.organos_treemap(repo_filters, q_folded=q_folded, top_organos=30)
    ]

    result = OrganosResult(
        organos=organos,
        total_organos=total_organos,
        importe_total=round(importe_total, 2),
        concentracion_top10=round(concentracion_top10, 2),
        treemap_breakdown=treemap_breakdown,
    )
    log.info("analytics_organos_done", total=total_organos)
    return result
