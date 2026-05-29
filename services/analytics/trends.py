"""Trends analytics — monthly/weekly evolution, heatmap data, forecast."""

from __future__ import annotations

from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TrendsFilters(BaseModel):
    """Query filters for trends."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    group_by: Literal["month", "week"] = "month"


class TrendPoint(BaseModel):
    """Single point in the time series."""

    period: str
    count: int
    importe: float


class HeatmapCell(BaseModel):
    """Single cell in the month x estado heatmap."""

    row: str
    col: str
    value: int


class TrendsResult(BaseModel):
    """Combined trends response."""

    series: list[TrendPoint] = Field(default_factory=list)
    heatmap: list[HeatmapCell] = Field(default_factory=list)
    yoy_count: float = 0.0
    yoy_importe: float = 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["fecha_publicacion"] = pd.to_datetime(
            df["fecha_publicacion"],
            errors="coerce",
            utc=True,
        )
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    return df


def _apply_filters(df: pd.DataFrame, filters: TrendsFilters) -> pd.DataFrame:
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
    return df


def _build_series(df: pd.DataFrame, freq: str) -> list[TrendPoint]:
    if df.empty or df["fecha_publicacion"].isna().all():
        return []
    work = df.dropna(subset=["fecha_publicacion"]).copy()
    period_key = "M" if freq == "month" else "W"
    work["period"] = work["fecha_publicacion"].dt.to_period(period_key).dt.to_timestamp()
    g = (
        work.groupby("period")
        .agg(count=("id_externo", "count"), importe=("importe", "sum"))
        .reset_index()
        .sort_values("period")
    )
    fmt = "%Y-%m" if freq == "month" else "%Y-W%V"
    return [
        TrendPoint(
            period=row["period"].strftime(fmt),
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
        )
        for _, row in g.iterrows()
    ]


def _build_heatmap(df: pd.DataFrame) -> list[HeatmapCell]:
    if df.empty or df["fecha_publicacion"].isna().all():
        return []
    work = df.dropna(subset=["fecha_publicacion"]).copy()
    work["mes"] = work["fecha_publicacion"].dt.to_period("M").astype(str)
    if "estado" not in work.columns:
        return []
    ct = work.groupby(["mes", "estado"]).size().reset_index(name="value")
    return [
        HeatmapCell(row=r["mes"], col=r["estado"], value=int(r["value"])) for _, r in ct.iterrows()
    ]


def _yoy(df: pd.DataFrame, days: int = 365) -> tuple[float, float]:
    """YoY delta for count and importe."""
    if df.empty:
        return 0.0, 0.0
    hoy = pd.Timestamp.now("UTC")
    cur = df[df["fecha_publicacion"] >= (hoy - pd.Timedelta(days=days))]
    prev = df[
        (df["fecha_publicacion"] < (hoy - pd.Timedelta(days=days)))
        & (df["fecha_publicacion"] >= (hoy - pd.Timedelta(days=days * 2)))
    ]
    cnt_cur, cnt_prev = len(cur), len(prev)
    imp_cur = float(cur["importe"].sum(skipna=True))
    imp_prev = float(prev["importe"].sum(skipna=True))
    yoy_count = ((cnt_cur - cnt_prev) / cnt_prev * 100) if cnt_prev else 0.0
    yoy_importe = ((imp_cur - imp_prev) / imp_prev * 100) if imp_prev else 0.0
    return yoy_count, yoy_importe


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_trends(filters: TrendsFilters) -> TrendsResult:
    """Compute time-series trends, heatmap, and YoY deltas."""
    log.info("analytics_trends_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    freq = filters.group_by
    series = _build_series(df, freq)
    heatmap = _build_heatmap(df)
    yoy_count, yoy_importe = _yoy(df)

    result = TrendsResult(
        series=series,
        heatmap=heatmap,
        yoy_count=yoy_count,
        yoy_importe=yoy_importe,
    )
    log.info("analytics_trends_done", points=len(result.series))
    return result
