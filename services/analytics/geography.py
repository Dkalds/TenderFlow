"""Geography analytics — distribution by CCAA."""

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


class GeoFilters(BaseModel):
    """Query filters for geography."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    tecnologia: str | None = None


class GeoEntry(BaseModel):
    """Single CCAA entry."""

    ccaa: str
    count: int
    importe: float
    pct: float


class ProvinciaEntry(BaseModel):
    """Single provincia entry (aggregated over the full filtered dataset)."""

    provincia: str
    count: int
    importe: float


class GeoResult(BaseModel):
    """Combined geography response."""

    by_ccaa: list[GeoEntry] = Field(default_factory=list)
    by_provincia: list[ProvinciaEntry] = Field(default_factory=list)
    concentracion_top3: float = 0.0
    ccaa_mas_activa: str | None = None


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


def _apply_filters(df: pd.DataFrame, filters: GeoFilters) -> pd.DataFrame:
    if df.empty:
        return df
    if filters.fecha_desde is not None:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_publicacion"] >= ts]
    if filters.fecha_hasta is not None:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_publicacion"] <= ts]
    if filters.tecnologia:
        df = df[df["tecnologia"] == filters.tecnologia]
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_geography(filters: GeoFilters) -> GeoResult:
    """Compute geographic distribution by CCAA."""
    log.info("analytics_geography_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty or "ccaa" not in df.columns:
        log.info("analytics_geography_done", entries=0)
        return GeoResult()

    g = (
        df.groupby("ccaa")
        .agg(count=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("count", ascending=False)
        .reset_index()
    )
    total = int(g["count"].sum())
    entries = [
        GeoEntry(
            ccaa=row["ccaa"],
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
            pct=float(row["count"] / total * 100) if total else 0.0,
        )
        for _, row in g.iterrows()
    ]

    top3_pct = sum(e.pct for e in entries[:3])
    most_active = entries[0].ccaa if entries else None

    # Agregación por provincia sobre TODO el dataset filtrado (antes el frontend
    # sumaba un sample de `licitaciones?limit=500` que ignoraba los filtros).
    by_provincia: list[ProvinciaEntry] = []
    if "provincia" in df.columns:
        pv = df.dropna(subset=["provincia"])
        pv = pv[pv["provincia"].astype(str).str.strip() != ""]
        if not pv.empty:
            pg = (
                pv.groupby("provincia")
                .agg(count=("id_externo", "count"), importe=("importe", "sum"))
                .sort_values("count", ascending=False)
                .reset_index()
            )
            by_provincia = [
                ProvinciaEntry(
                    provincia=str(row["provincia"]),
                    count=int(row["count"]),
                    importe=float(row["importe"] or 0),
                )
                for _, row in pg.iterrows()
            ]

    result = GeoResult(
        by_ccaa=entries,
        by_provincia=by_provincia,
        concentracion_top3=top3_pct,
        ccaa_mas_activa=most_active,
    )
    log.info("analytics_geography_done", entries=len(entries))
    return result
