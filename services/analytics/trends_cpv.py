"""Trends CPV analytics — per-CPV time series.

Agrega en Postgres vía :class:`AggregateRepository` (ADR-023); hasta 2026-08
cargaba la tabla completa a pandas en el proceso API — bloqueado en Render por
el cortacircuitos full-table, que dejaba el endpoint vacío en producción.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AggregateRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TrendsCpvFilters(BaseModel):
    cpv: str | None = None
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    top_n: int = 15


class CpvSeriesPoint(BaseModel):
    period: str
    count: int
    importe: float


class CpvSeries(BaseModel):
    cpv: str
    label: str
    series: list[CpvSeriesPoint] = Field(default_factory=list)


class CpvImporteRank(BaseModel):
    cpv: str
    importe_total: float
    count: int


class CpvSummary(BaseModel):
    total_cpvs: int = 0
    periodo_inicio: str | None = None
    periodo_fin: str | None = None


class TrendsCpvResult(BaseModel):
    series_by_cpv: list[CpvSeries] = Field(default_factory=list)
    top_cpv_by_importe: list[CpvImporteRank] = Field(default_factory=list)
    summary: CpvSummary = Field(default_factory=CpvSummary)


def _to_repo_filters(filters: TrendsCpvFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
        cpv=filters.cpv,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_trends_cpv(filters: TrendsCpvFilters) -> TrendsCpvResult:
    """Per-CPV time series and rankings."""
    log.info("analytics_trends_cpv_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)

    total_cpvs, top, inicio, fin = _repo.trends_cpv_ranking(repo_filters, top_n=filters.top_n)
    if total_cpvs == 0:
        return TrendsCpvResult()

    top_cpv_by_importe = [
        CpvImporteRank(
            cpv=str(r["cpv"]),
            importe_total=float(r["importe_total"] or 0),
            count=int(r["count"]),
        )
        for r in top
    ]

    series_rows = _repo.trends_cpv_series(repo_filters, cpvs=[str(r["cpv"]) for r in top])
    by_cpv: dict[str, list[CpvSeriesPoint]] = {}
    for r in series_rows:
        by_cpv.setdefault(str(r["cpv"]), []).append(
            CpvSeriesPoint(
                period=str(r["mes"]),
                count=int(r["count"]),
                importe=float(r["importe"] or 0),
            )
        )
    series_by_cpv = [
        CpvSeries(cpv=cpv_val, label=cpv_val, series=points) for cpv_val, points in by_cpv.items()
    ]

    summary = CpvSummary(total_cpvs=total_cpvs, periodo_inicio=inicio, periodo_fin=fin)

    log.info("analytics_trends_cpv_done", cpvs=len(series_by_cpv))
    return TrendsCpvResult(
        series_by_cpv=series_by_cpv,
        top_cpv_by_importe=top_cpv_by_importe,
        summary=summary,
    )
