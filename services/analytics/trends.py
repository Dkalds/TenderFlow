"""Trends analytics — monthly/weekly evolution, heatmap data, forecast."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

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
    group_by: Literal["month", "week", "day"] = "month"


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


class WaterfallPoint(BaseModel):
    """Month-to-month delta."""

    period: str
    delta: int
    cumulative: int


class HistogramBin(BaseModel):
    """Importe distribution bin."""

    bin_label: str
    count: int


class TrendsResult(BaseModel):
    """Combined trends response."""

    series: list[TrendPoint] = Field(default_factory=list)
    heatmap: list[HeatmapCell] = Field(default_factory=list)
    yoy_count: float = 0.0
    yoy_importe: float = 0.0
    waterfall: list[WaterfallPoint] = Field(default_factory=list)
    histogram_bins: list[HistogramBin] = Field(default_factory=list)
    mes_pico: dict[str, Any] | None = None


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
    period_key = {"month": "M", "week": "W", "day": "D"}.get(freq, "M")
    work["period"] = work["fecha_publicacion"].dt.to_period(period_key).dt.to_timestamp()
    g = (
        work.groupby("period")
        .agg(count=("id_externo", "count"), importe=("importe", "sum"))
        .reset_index()
        .sort_values("period")
    )
    fmt = {"month": "%Y-%m", "week": "%Y-W%V", "day": "%Y-%m-%d"}.get(freq, "%Y-%m")
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


def _build_waterfall(series: list[TrendPoint]) -> list[WaterfallPoint]:
    """Build waterfall (month-to-month delta) from series."""
    if not series:
        return []
    result: list[WaterfallPoint] = []
    cumulative = 0
    prev_count = 0
    for i, pt in enumerate(series):
        delta = pt.count - prev_count if i > 0 else pt.count
        cumulative += delta
        result.append(WaterfallPoint(period=pt.period, delta=delta, cumulative=cumulative))
        prev_count = pt.count
    return result


def _build_histogram(df: pd.DataFrame) -> list[HistogramBin]:
    """Build log-scale histogram bins for importe."""
    if df.empty:
        return []
    valid = df["importe"].dropna()
    if valid.empty:
        return []
    bins = [0, 1_000, 10_000, 50_000, 100_000, 500_000, 1_000_000, 5_000_000, float("inf")]
    labels = ["0-1K", "1K-10K", "10K-50K", "50K-100K", "100K-500K", "500K-1M", "1M-5M", "5M+"]
    counts = (
        pd.cut(valid, bins=bins, labels=labels, right=False)
        .value_counts()
        .reindex(labels, fill_value=0)
    )
    return [HistogramBin(bin_label=str(label), count=int(c)) for label, c in counts.items()]


def _find_mes_pico(df: pd.DataFrame) -> dict[str, Any] | None:
    """Find the month with highest total importe."""
    if df.empty or df["fecha_publicacion"].isna().all():
        return None
    work = df.dropna(subset=["fecha_publicacion"]).copy()
    work["mes"] = work["fecha_publicacion"].dt.to_period("M").dt.to_timestamp()
    g = (
        work.groupby("mes")
        .agg(importe=("importe", "sum"), count=("id_externo", "count"))
        .reset_index()
    )
    if g.empty:
        return None
    best = g.loc[g["importe"].idxmax()]
    return {
        "mes": best["mes"].strftime("%Y-%m"),
        "importe": float(best["importe"] or 0),
        "count": int(best["count"]),
    }


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
        waterfall=_build_waterfall(series),
        histogram_bins=_build_histogram(df),
        mes_pico=_find_mes_pico(df),
    )
    log.info("analytics_trends_done", points=len(result.series))
    return result
