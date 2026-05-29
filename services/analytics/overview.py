"""Analytics overview service — ports dashboard/stats/_base.py aggregations.

Converts the pandas-based in-memory analytics to service functions that
can be called from API endpoints. Uses services.licitaciones for data loading.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OverviewFilters(BaseModel):
    """Query filters for the overview endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None


class EstadoCount(BaseModel):
    """Count per estado."""

    estado: str
    n: int


class MesAggregate(BaseModel):
    """Monthly aggregate."""

    mes: str
    n_licitaciones: int
    importe: float


class OrganoAggregate(BaseModel):
    """Top organo aggregate."""

    organo_contratacion: str
    n: int
    importe: float


class FunnelStep(BaseModel):
    """Funnel step with absolute count and percentage."""

    estado: str
    n: int
    pct: float


class OverviewResult(BaseModel):
    """Combined overview response."""

    total_licitaciones: int = 0
    importe_total: float = 0.0
    importe_medio: float = 0.0
    organos_unicos: int = 0
    yoy_delta: float = 0.0
    licitaciones_30d: int = 0
    importe_30d: float = 0.0
    por_estado: list[EstadoCount] = Field(default_factory=list)
    por_mes: list[MesAggregate] = Field(default_factory=list)
    top_organos: list[OrganoAggregate] = Field(default_factory=list)
    funnel_estados: list[FunnelStep] = Field(default_factory=list)
    hhi: float = 0.0
    pct_oferta_unica: float = 0.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    """Load stats dataframe from the service layer."""
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


def _apply_filters(df: pd.DataFrame, filters: OverviewFilters) -> pd.DataFrame:
    """Apply optional filters to the dataframe."""
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
    if filters.estado:
        df = df[df["estado"] == filters.estado]
    return df


# ---------------------------------------------------------------------------
# Aggregation functions (ported from dashboard/stats/_base.py)
# ---------------------------------------------------------------------------


def _kpis(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {"total": 0, "importe_total": 0.0, "importe_medio": 0.0, "organos": 0}
    return {
        "total": len(df),
        "importe_total": float(df["importe"].sum(skipna=True)),
        "importe_medio": float(df["importe"].mean(skipna=True) or 0),
        "organos": int(df["organo_contratacion"].nunique()),
    }


def _por_estado(df: pd.DataFrame) -> list[EstadoCount]:
    if df.empty:
        return []
    counts = df.groupby("estado").size().reset_index(name="n").sort_values("n", ascending=False)
    return [EstadoCount(estado=row["estado"], n=int(row["n"])) for _, row in counts.iterrows()]


def _por_mes(df: pd.DataFrame) -> list[MesAggregate]:
    if df.empty or df["fecha_publicacion"].isna().all():
        return []
    g = (
        df.dropna(subset=["fecha_publicacion"])
        .assign(mes=lambda x: x["fecha_publicacion"].dt.to_period("M").dt.to_timestamp())
        .groupby("mes")
        .agg(n_licitaciones=("id_externo", "count"), importe=("importe", "sum"))
        .reset_index()
        .sort_values("mes")
    )
    return [
        MesAggregate(
            mes=row["mes"].strftime("%Y-%m"),
            n_licitaciones=int(row["n_licitaciones"]),
            importe=float(row["importe"] or 0),
        )
        for _, row in g.iterrows()
    ]


def _top_organos(df: pd.DataFrame, n: int = 15) -> list[OrganoAggregate]:
    if df.empty:
        return []
    g = (
        df.groupby("organo_contratacion")
        .agg(n=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("n", ascending=False)
        .head(n)
        .reset_index()
    )
    return [
        OrganoAggregate(
            organo_contratacion=row["organo_contratacion"],
            n=int(row["n"]),
            importe=float(row["importe"] or 0),
        )
        for _, row in g.iterrows()
    ]


def _funnel_estados(df: pd.DataFrame) -> list[FunnelStep]:
    if df.empty:
        return []
    order = ["PUB", "EV", "RES", "ADJ", "ANUL"]
    counts = df["estado"].value_counts()
    total = len(df)
    return [
        FunnelStep(
            estado=est,
            n=int(counts.get(est, 0)),
            pct=float(counts.get(est, 0) / total * 100) if total else 0.0,
        )
        for est in order
    ]


def _yoy_delta_count(df: pd.DataFrame, days: int = 30) -> tuple[float, float]:
    """Returns (current_count, pct_change) for last N days vs previous N days."""
    if df.empty:
        return 0.0, 0.0
    hoy = pd.Timestamp.now("UTC")
    ult = df[df["fecha_publicacion"] >= (hoy - pd.Timedelta(days=days))]
    prev = df[
        (df["fecha_publicacion"] < (hoy - pd.Timedelta(days=days)))
        & (df["fecha_publicacion"] >= (hoy - pd.Timedelta(days=days * 2)))
    ]
    v_act = float(len(ult))
    v_prev = float(len(prev))
    pct = ((v_act - v_prev) / v_prev * 100) if v_prev else 0.0
    return v_act, pct


def _importe_30d(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    hoy = pd.Timestamp.now("UTC")
    ult = df[df["fecha_publicacion"] >= (hoy - pd.Timedelta(days=30))]
    return float(ult["importe"].sum(skipna=True))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_overview(filters: OverviewFilters) -> OverviewResult:
    """Compute the full overview dashboard payload."""
    log.info("analytics_overview_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    k = _kpis(df)
    lics_30d, yoy = _yoy_delta_count(df)

    result = OverviewResult(
        total_licitaciones=k["total"],
        importe_total=k["importe_total"],
        importe_medio=k["importe_medio"],
        organos_unicos=k["organos"],
        yoy_delta=yoy,
        licitaciones_30d=int(lics_30d),
        importe_30d=_importe_30d(df),
        por_estado=_por_estado(df),
        por_mes=_por_mes(df),
        top_organos=_top_organos(df),
        funnel_estados=_funnel_estados(df),
        hhi=0.0,  # Requires adjudicaciones data — placeholder
        pct_oferta_unica=0.0,  # Requires adjudicaciones data — placeholder
    )
    log.info("analytics_overview_done", total=result.total_licitaciones)
    return result
