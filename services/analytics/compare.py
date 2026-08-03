"""Compare periods analytics — side-by-side period comparison.

Agrega en Postgres (ADR-023) reutilizando ``AggregateRepository.overview_kpis``
— dos llamadas con rangos de fecha distintos. Hasta 2026-08 cargaba la tabla
completa a pandas en el proceso API (vacío en producción por el
cortacircuitos full-table de Render).
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


class CompareFilters(BaseModel):
    range_a_desde: date
    range_a_hasta: date
    range_b_desde: date
    range_b_hasta: date
    ccaa: str | None = None
    tecnologia: str | None = None


class PeriodStats(BaseModel):
    total: int = 0
    importe_total: float = 0.0
    importe_medio: float = 0.0
    organos: int = 0


class PeriodDeltas(BaseModel):
    total_pct: float = 0.0
    importe_total_pct: float = 0.0
    importe_medio_pct: float = 0.0
    organos_pct: float = 0.0


class CompareResult(BaseModel):
    period_a: PeriodStats = Field(default_factory=PeriodStats)
    period_b: PeriodStats = Field(default_factory=PeriodStats)
    deltas: PeriodDeltas = Field(default_factory=PeriodDeltas)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _period_stats(filters: CompareFilters, desde: date, hasta: date) -> PeriodStats:
    kpis = _repo.overview_kpis(
        LicitacionesFilters(
            fecha_desde=desde.isoformat(),
            fecha_hasta=hasta.isoformat(),
            ccaa=filters.ccaa,
            tecnologia=filters.tecnologia,
        )
    )
    return PeriodStats(
        total=int(kpis["total"]),
        importe_total=float(kpis["importe_total"]),
        importe_medio=float(kpis["importe_medio"]),
        organos=int(kpis["organos"]),
    )


def _pct_delta(a: float, b: float) -> float:
    if a == 0:
        return 0.0
    return ((b - a) / abs(a)) * 100


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_compare_periods(filters: CompareFilters) -> CompareResult:
    """Compare two time periods side-by-side."""
    log.info("analytics_compare_start", filters=filters.model_dump(exclude_none=True))

    pa = _period_stats(filters, filters.range_a_desde, filters.range_a_hasta)
    pb = _period_stats(filters, filters.range_b_desde, filters.range_b_hasta)

    deltas = PeriodDeltas(
        total_pct=_pct_delta(pa.total, pb.total),
        importe_total_pct=_pct_delta(pa.importe_total, pb.importe_total),
        importe_medio_pct=_pct_delta(pa.importe_medio, pb.importe_medio),
        organos_pct=_pct_delta(pa.organos, pb.organos),
    )

    log.info("analytics_compare_done")
    return CompareResult(period_a=pa, period_b=pb, deltas=deltas)
