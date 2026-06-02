"""Organos analytics — ranking of contracting bodies."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OrganosFilters(BaseModel):
    """Query filters for organos endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    limit: int = 50


class OrganoEntry(BaseModel):
    """Single organo ranking entry."""

    organo_contratacion: str
    count: int
    importe: float
    pct: float
    ccaa: str | None = None


class OrganosResult(BaseModel):
    """Combined organos response."""

    organos: list[OrganoEntry] = Field(default_factory=list)
    total_organos: int = 0
    concentracion_top10: float = 0.0


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


def _apply_filters(df: pd.DataFrame, filters: OrganosFilters) -> pd.DataFrame:
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_organos(filters: OrganosFilters) -> OrganosResult:
    """Compute organo ranking with concentration metrics."""
    log.info("analytics_organos_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        log.info("analytics_organos_done", total=0)
        return OrganosResult()

    total = len(df)
    total_organos = int(df["organo_contratacion"].nunique())

    # Group by organo
    g = (
        df.groupby("organo_contratacion")
        .agg(count=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("count", ascending=False)
        .reset_index()
    )
    g["pct"] = g["count"] / total * 100

    # Most common ccaa per organo
    ccaa_mode = (
        df.dropna(subset=["ccaa"])
        .groupby("organo_contratacion")["ccaa"]
        .agg(lambda x: x.mode().iloc[0] if not x.mode().empty else "")
    )

    # Concentration of top 10
    concentracion_top10 = float(g.head(10)["pct"].sum()) if len(g) >= 10 else float(g["pct"].sum())

    # Limit results
    g_limited = g.head(filters.limit)

    organos = [
        OrganoEntry(
            organo_contratacion=row["organo_contratacion"],
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
            pct=round(float(row["pct"]), 2),
            ccaa=ccaa_mode.get(row["organo_contratacion"]),
        )
        for _, row in g_limited.iterrows()
    ]

    result = OrganosResult(
        organos=organos,
        total_organos=total_organos,
        concentracion_top10=round(concentracion_top10, 2),
    )
    log.info("analytics_organos_done", total=total_organos)
    return result
