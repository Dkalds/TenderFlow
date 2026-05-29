"""Competitor analytics — market share, HHI, bidder rankings."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class CompetitorFilters(BaseModel):
    """Query filters for competitor analysis."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    limit: int = 20


class CompetitorEntry(BaseModel):
    """Single competitor entry."""

    nombre: str
    count: int
    importe: float
    cuota: float


class CompetitorResult(BaseModel):
    """Combined competitor response."""

    competitors: list[CompetitorEntry] = Field(default_factory=list)
    hhi: float = 0.0
    pct_oferta_unica: float = 0.0
    total_adjudicaciones: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df(ccaa: str | None) -> pd.DataFrame:
    ccaa_filter = (ccaa,) if ccaa else None
    rows = load_raw_adjudicaciones(ccaa_filter=ccaa_filter)
    df = pd.DataFrame(rows)
    if not df.empty:
        if "fecha_adjudicacion" in df.columns:
            df["fecha_adjudicacion"] = pd.to_datetime(
                df["fecha_adjudicacion"],
                errors="coerce",
                utc=True,
            )
        df["importe"] = pd.to_numeric(
            df.get("importe_adjudicacion", df.get("importe", pd.Series(dtype=float))),
            errors="coerce",
        )
        if "empresa" not in df.columns and "adjudicatario" in df.columns:
            df["empresa"] = df["adjudicatario"]
    return df


def _apply_filters(df: pd.DataFrame, filters: CompetitorFilters) -> pd.DataFrame:
    if df.empty:
        return df
    if filters.fecha_desde is not None and "fecha_adjudicacion" in df.columns:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_adjudicacion"] >= ts]
    if filters.fecha_hasta is not None and "fecha_adjudicacion" in df.columns:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_adjudicacion"] <= ts]
    return df


def _compute_hhi(shares: pd.Series) -> float:  # type: ignore[type-arg]
    """Herfindahl-Hirschman Index from market share percentages (0-10000)."""
    return float((shares**2).sum())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_competitors(filters: CompetitorFilters) -> CompetitorResult:
    """Compute competitor rankings, HHI, and single-bid percentage."""
    log.info("analytics_competitors_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df(filters.ccaa)
    df = _apply_filters(df, filters)

    if df.empty or "empresa" not in df.columns:
        log.info("analytics_competitors_done", total=0)
        return CompetitorResult()

    total = len(df)

    # Group by empresa
    g = (
        df.groupby("empresa")
        .agg(count=("empresa", "count"), importe=("importe", "sum"))
        .sort_values("count", ascending=False)
        .reset_index()
    )

    total_importe = float(g["importe"].sum(skipna=True)) or 1.0
    g["cuota"] = g["importe"] / total_importe * 100

    entries = [
        CompetitorEntry(
            nombre=row["empresa"],
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
            cuota=float(row["cuota"]),
        )
        for _, row in g.head(filters.limit).iterrows()
    ]

    hhi = _compute_hhi(g["cuota"])

    # Single-bid percentage: licitaciones with only one bidder
    pct_unica = 0.0
    if "id_externo" in df.columns:
        bids_per_lic = df.groupby("id_externo")["empresa"].nunique()
        single_bid = int((bids_per_lic == 1).sum())
        total_lics = len(bids_per_lic)
        pct_unica = (single_bid / total_lics * 100) if total_lics else 0.0

    result = CompetitorResult(
        competitors=entries,
        hhi=hhi,
        pct_oferta_unica=pct_unica,
        total_adjudicaciones=total,
    )
    log.info("analytics_competitors_done", total=total, hhi=hhi)
    return result
