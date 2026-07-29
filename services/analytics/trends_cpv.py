"""Trends CPV analytics — per-CPV time series."""

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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    return load_stats_base_df()


def _apply_filters(df: pd.DataFrame, filters: TrendsCpvFilters) -> pd.DataFrame:
    if df.empty:
        return df
    if filters.fecha_desde is not None:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_publicacion"] >= ts]
    if filters.fecha_hasta is not None:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_publicacion"] <= ts]
    if filters.ccaa:
        df = df[df["ccaa"] == filters.ccaa]
    if filters.tecnologia:
        df = df[df["tecnologia"] == filters.tecnologia]
    if filters.cpv:
        df = df[df["cpv"] == filters.cpv]
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_trends_cpv(filters: TrendsCpvFilters) -> TrendsCpvResult:
    """Per-CPV time series and rankings."""
    log.info("analytics_trends_cpv_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty or "cpv" not in df.columns:
        return TrendsCpvResult()

    work = df.dropna(subset=["cpv", "fecha_publicacion"]).copy()
    if work.empty:
        return TrendsCpvResult()

    work["period"] = work["fecha_publicacion"].dt.to_period("M").dt.to_timestamp()

    # Top N CPVs by importe
    cpv_agg = (
        work.groupby("cpv")
        .agg(importe_total=("importe", "sum"), count=("id_externo", "count"))
        .sort_values("importe_total", ascending=False)
        .reset_index()
    )

    total_cpvs = len(cpv_agg)
    top_cpvs = cpv_agg.head(filters.top_n)

    top_cpv_by_importe = [
        CpvImporteRank(
            cpv=str(row["cpv"]),
            importe_total=float(row["importe_total"] or 0),
            count=int(row["count"]),
        )
        for _, row in top_cpvs.iterrows()
    ]

    # Time series per top CPV
    top_cpv_set = set(top_cpvs["cpv"].tolist())
    filtered = work[work["cpv"].isin(top_cpv_set)]

    series_by_cpv: list[CpvSeries] = []
    for cpv_val, grp in filtered.groupby("cpv"):
        monthly = (
            grp.groupby("period")
            .agg(count=("id_externo", "count"), importe=("importe", "sum"))
            .reset_index()
            .sort_values("period")
        )
        points = [
            CpvSeriesPoint(
                period=row["period"].strftime("%Y-%m"),
                count=int(row["count"]),
                importe=float(row["importe"] or 0),
            )
            for _, row in monthly.iterrows()
        ]
        series_by_cpv.append(CpvSeries(cpv=str(cpv_val), label=str(cpv_val), series=points))

    # Summary
    periods = work["period"].dropna()
    summary = CpvSummary(
        total_cpvs=total_cpvs,
        periodo_inicio=periods.min().strftime("%Y-%m") if not periods.empty else None,
        periodo_fin=periods.max().strftime("%Y-%m") if not periods.empty else None,
    )

    log.info("analytics_trends_cpv_done", cpvs=len(series_by_cpv))
    return TrendsCpvResult(
        series_by_cpv=series_by_cpv,
        top_cpv_by_importe=top_cpv_by_importe,
        summary=summary,
    )
