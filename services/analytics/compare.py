"""Compare periods analytics — side-by-side period comparison."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_base_df

log = get_logger(__name__)


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


def _load_df() -> pd.DataFrame:
    return load_stats_base_df()


def _period_stats(df: pd.DataFrame, desde: date, hasta: date) -> PeriodStats:
    if df.empty:
        return PeriodStats()
    ts_desde = pd.Timestamp(desde, tz="UTC")
    ts_hasta = pd.Timestamp(hasta, tz="UTC")
    subset = df[(df["fecha_publicacion"] >= ts_desde) & (df["fecha_publicacion"] <= ts_hasta)]
    if subset.empty:
        return PeriodStats()
    total = len(subset)
    imp_total = float(subset["importe"].sum(skipna=True))
    imp_medio = float(subset["importe"].mean(skipna=True) or 0)
    organos = (
        int(subset["organo_contratacion"].nunique())
        if "organo_contratacion" in subset.columns
        else 0
    )
    return PeriodStats(
        total=total, importe_total=imp_total, importe_medio=imp_medio, organos=organos
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
    df = _load_df()

    if not df.empty:
        if filters.ccaa:
            df = df[df["ccaa"] == filters.ccaa]
        if filters.tecnologia:
            df = df[df["tecnologia"] == filters.tecnologia]

    pa = _period_stats(df, filters.range_a_desde, filters.range_a_hasta)
    pb = _period_stats(df, filters.range_b_desde, filters.range_b_hasta)

    deltas = PeriodDeltas(
        total_pct=_pct_delta(pa.total, pb.total),
        importe_total_pct=_pct_delta(pa.importe_total, pb.importe_total),
        importe_medio_pct=_pct_delta(pa.importe_medio, pb.importe_medio),
        organos_pct=_pct_delta(pa.organos, pb.organos),
    )

    log.info("analytics_compare_done")
    return CompareResult(period_a=pa, period_b=pb, deltas=deltas)
