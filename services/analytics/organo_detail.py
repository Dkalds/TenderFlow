"""Organo detail analytics — drill-down for a single contracting body."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OrganoDetailFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class OrganoKpis(BaseModel):
    total_licitaciones: int = 0
    importe_total: float = 0.0
    pct_adjudicado: float = 0.0
    lead_time_medio: float | None = None


class TopAdjudicatario(BaseModel):
    nombre: str
    count: int
    importe: float


class Estacionalidad(BaseModel):
    mes_numero: int
    count: int


class TopScored(BaseModel):
    id_externo: str
    titulo: str | None = None
    importe: float | None = None
    score: float


class OrganoDetailResult(BaseModel):
    kpis: OrganoKpis = Field(default_factory=OrganoKpis)
    top_adjudicatarios: list[TopAdjudicatario] = Field(default_factory=list)
    estacionalidad: list[Estacionalidad] = Field(default_factory=list)
    top_scored: list[TopScored] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["fecha_publicacion"] = pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True)
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    return df


def _apply_filters(df: pd.DataFrame, filters: Any) -> pd.DataFrame:
    if df.empty:
        return df
    if getattr(filters, "fecha_desde", None) is not None:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_publicacion"] >= ts]
    if getattr(filters, "fecha_hasta", None) is not None:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_publicacion"] <= ts]
    if getattr(filters, "ccaa", None):
        df = df[df["ccaa"] == filters.ccaa]
    if getattr(filters, "tecnologia", None):
        df = df[df["tecnologia"] == filters.tecnologia]
    return df


def _simple_score(row: pd.Series) -> float:  # type: ignore[type-arg]
    """Simplified scoring for ranking within an organo."""
    score = 0.0
    if pd.notna(row.get("importe")):
        score += min(float(row["importe"]) / 1_000_000, 40)
    titulo = str(row.get("titulo", "") or "").lower()
    kw = ["sap", "erp", "cloud", "digital", "mantenimiento", "desarrollo"]
    score += sum(5 for k in kw if k in titulo)
    if row.get("estado") in ("PUB", "EV"):
        score += 10
    return min(round(score, 1), 100)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_organo_detail(organo: str, filters: OrganoDetailFilters) -> OrganoDetailResult:
    """Drill-down for a single contracting body."""
    log.info("analytics_organo_detail_start", organo=organo)
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        return OrganoDetailResult()

    df = df[df["organo_contratacion"] == organo]
    if df.empty:
        return OrganoDetailResult()

    # KPIs
    total = len(df)
    importe_total = float(df["importe"].sum(skipna=True))
    adjudicado = len(df[df["estado"] == "ADJ"]) if "estado" in df.columns else 0
    pct_adj = (adjudicado / total * 100) if total else 0.0

    kpis = OrganoKpis(
        total_licitaciones=total,
        importe_total=importe_total,
        pct_adjudicado=pct_adj,
        lead_time_medio=None,
    )

    # Adjudicatarios from adjudicaciones
    adj_rows = load_raw_adjudicaciones()
    adj_df = pd.DataFrame(adj_rows)
    top_adj: list[TopAdjudicatario] = []
    if not adj_df.empty:
        if "organo_contratacion" in adj_df.columns:
            adj_org = adj_df[adj_df["organo_contratacion"] == organo]
        else:
            adj_org = adj_df
        nombre_col = "nombre" if "nombre" in adj_org.columns else "adjudicatario"
        if nombre_col in adj_org.columns:
            adj_org_imp = adj_org.copy()
            adj_org_imp["importe"] = pd.to_numeric(
                adj_org_imp.get(
                    "importe_adjudicado", adj_org_imp.get("importe", pd.Series(dtype=float))
                ),
                errors="coerce",
            )
            g = (
                adj_org_imp.groupby(nombre_col)
                .agg(count=(nombre_col, "count"), importe=("importe", "sum"))
                .sort_values("count", ascending=False)
                .head(20)
                .reset_index()
            )
            top_adj = [
                TopAdjudicatario(
                    nombre=str(row[nombre_col]),
                    count=int(row["count"]),
                    importe=float(row["importe"] or 0),
                )
                for _, row in g.iterrows()
            ]

    # Estacionalidad
    estacionalidad: list[Estacionalidad] = []
    valid_dates = df.dropna(subset=["fecha_publicacion"])
    if not valid_dates.empty:
        valid_dates = valid_dates.copy()
        valid_dates["mes_num"] = valid_dates["fecha_publicacion"].dt.month
        n_years = max(valid_dates["fecha_publicacion"].dt.year.nunique(), 1)
        mes_counts = valid_dates.groupby("mes_num").size()
        estacionalidad = [
            Estacionalidad(mes_numero=int(m), count=round(c / n_years))
            for m, c in mes_counts.items()
        ]

    # Top scored
    df = df.copy()
    df["_score"] = df.apply(_simple_score, axis=1)
    top_scored_df = df.nlargest(30, "_score")
    top_scored = [
        TopScored(
            id_externo=str(row.get("id_externo", "")),
            titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
            importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
            score=float(row["_score"]),
        )
        for _, row in top_scored_df.iterrows()
    ]

    log.info("analytics_organo_detail_done", total=total)
    return OrganoDetailResult(
        kpis=kpis,
        top_adjudicatarios=top_adj,
        estacionalidad=estacionalidad,
        top_scored=top_scored,
    )
