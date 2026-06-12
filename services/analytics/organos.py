"""Organos analytics — ranking of contracting bodies."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe
from services.normalization import fold_text

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
    q: str | None = None
    limit: int = 50


class OrganoEntry(BaseModel):
    """Single organo ranking entry."""

    organo_contratacion: str
    count: int
    importe: float
    pct: float
    ccaa: str | None = None


class TreemapItem(BaseModel):
    """Single cell in the organo → tipo_contrato treemap breakdown."""

    organo: str
    tipo_contrato: str
    importe: float


class OrganosResult(BaseModel):
    """Combined organos response."""

    organos: list[OrganoEntry] = Field(default_factory=list)
    total_organos: int = 0
    concentracion_top10: float = 0.0
    treemap_breakdown: list[TreemapItem] = Field(default_factory=list)


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


def _fold_series(s: pd.Series) -> pd.Series:
    """Versión vectorizada de fold_text: sin tildes + casefold, NaN → ""."""
    return (
        s.fillna("")
        .str.normalize("NFKD")
        .str.encode("ascii", "ignore")
        .str.decode("ascii")
        .str.casefold()
    )


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
    if filters.q:
        # Matching accent/case-insensitive sobre el nombre del órgano,
        # ANTES de agrupar/limitar: así un órgano fuera del top-N sigue
        # siendo encontrable ("Informatica" matchea "Informática").
        mask = _fold_series(df["organo_contratacion"]).str.contains(
            fold_text(filters.q), regex=False
        )
        df = df[mask]
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

    # Treemap breakdown: top 30 organos x tipo_contrato
    treemap_breakdown: list[TreemapItem] = []
    if "tipo_contrato" in df.columns:
        top30_organos = set(g.head(30)["organo_contratacion"])
        tm_df = df[df["organo_contratacion"].isin(top30_organos)].dropna(
            subset=["importe", "tipo_contrato"]
        )
        if not tm_df.empty:
            tm_g = (
                tm_df.groupby(["organo_contratacion", "tipo_contrato"])["importe"]
                .sum()
                .reset_index()
            )
            treemap_breakdown = [
                TreemapItem(
                    organo=str(row["organo_contratacion"]),
                    tipo_contrato=str(row["tipo_contrato"]),
                    importe=float(row["importe"]),
                )
                for _, row in tm_g.iterrows()
                if float(row["importe"]) > 0
            ]

    result = OrganosResult(
        organos=organos,
        total_organos=total_organos,
        concentracion_top10=round(concentracion_top10, 2),
        treemap_breakdown=treemap_breakdown,
    )
    log.info("analytics_organos_done", total=total_organos)
    return result
