"""Organo detail analytics — drill-down for a single contracting body."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.classification import (
    ESTADO_LABELS,
    cpv_label,
    detect_project_type,
    tipo_contrato_label,
)
from services.licitaciones import load_stats_base_df

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
    importe_medio: float = 0.0
    pct_adjudicado: float = 0.0
    lead_time_medio: float | None = None
    top_adjudicatario: str | None = None
    top_adj_importe: float = 0.0


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
    ccaa: str | None = None
    estado: str | None = None
    estado_desc: str | None = None
    banda: str | None = None
    empresa: str | None = None
    baja_pct: float | None = None
    fecha_adjudicacion: str | None = None
    modulos_str: str | None = None
    url: str | None = None
    tipo_proyecto: str | None = None
    tipo_contrato_desc: str | None = None
    cpv_desc: str | None = None


class OrganoDetailResult(BaseModel):
    kpis: OrganoKpis = Field(default_factory=OrganoKpis)
    top_adjudicatarios: list[TopAdjudicatario] = Field(default_factory=list)
    estacionalidad: list[Estacionalidad] = Field(default_factory=list)
    top_scored: list[TopScored] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    df = load_stats_base_df()
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


def _simple_score(row: pd.Series) -> float:
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


def _score_to_banda(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    return "D"


def _lead_time_median(adj_df: pd.DataFrame) -> float | None:
    """Mediana de días entre publicación y adjudicación.

    Espera un DataFrame de adjudicaciones con columnas ``fecha_publicacion``
    (de la licitación asociada) y ``fecha_adjudicacion``. Solo cuenta diferencias
    positivas. Devuelve ``None`` si no hay pares válidos.
    """
    if adj_df.empty:
        return None
    if "fecha_publicacion" not in adj_df.columns or "fecha_adjudicacion" not in adj_df.columns:
        return None
    fp = pd.to_datetime(adj_df["fecha_publicacion"], errors="coerce", utc=True)
    fa = pd.to_datetime(adj_df["fecha_adjudicacion"], errors="coerce", utc=True)
    diff = (fa - fp).dt.days
    valid = diff[diff > 0]
    if valid.empty:
        return None
    return float(valid.median())


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
    notna_imp = int(df["importe"].notna().sum())
    importe_medio = float(importe_total / notna_imp) if notna_imp else 0.0
    adjudicado = len(df[df["estado"] == "ADJ"]) if "estado" in df.columns else 0
    pct_adj = (adjudicado / total * 100) if total else 0.0

    kpis = OrganoKpis(
        total_licitaciones=total,
        importe_total=importe_total,
        importe_medio=importe_medio,
        pct_adjudicado=pct_adj,
        lead_time_medio=None,
    )

    # Adjudicatarios from adjudicaciones
    adj_rows = load_raw_adjudicaciones()
    adj_df = pd.DataFrame(adj_rows)
    top_adj: list[TopAdjudicatario] = []

    if not adj_df.empty:
        # Normalise importe column
        imp_col = "importe_adjudicado" if "importe_adjudicado" in adj_df.columns else "importe"
        if imp_col in adj_df.columns:
            adj_df["_importe"] = pd.to_numeric(adj_df[imp_col], errors="coerce")
        else:
            adj_df["_importe"] = float("nan")

        # Filter to this organ
        if "organo_contratacion" in adj_df.columns:
            adj_org = adj_df[adj_df["organo_contratacion"] == organo].copy()
        else:
            adj_org = adj_df.copy()

        nombre_col = (
            "nombre_canonico"
            if "nombre_canonico" in adj_org.columns
            else ("nombre" if "nombre" in adj_org.columns else "adjudicatario")
        )

        if nombre_col in adj_org.columns:
            g = (
                adj_org.groupby(nombre_col)
                .agg(count=(nombre_col, "count"), importe=("_importe", "sum"))
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

        # Lead time mediano (pub → adj) sobre las adjudicaciones del órgano
        kpis.lead_time_medio = _lead_time_median(adj_org)

    # Top adjudicatario en kpis
    if top_adj:
        kpis.top_adjudicatario = top_adj[0].nombre
        kpis.top_adj_importe = top_adj[0].importe

    # Estacionalidad
    estacionalidad: list[Estacionalidad] = []
    valid_dates = df.dropna(subset=["fecha_publicacion"])
    if not valid_dates.empty:
        valid_dates = valid_dates.copy()
        valid_dates["mes_num"] = valid_dates["fecha_publicacion"].dt.month
        n_years = max(valid_dates["fecha_publicacion"].dt.year.nunique(), 1)
        mes_counts = valid_dates.groupby("mes_num").size()
        estacionalidad = [
            Estacionalidad(mes_numero=int(str(m)), count=round(c / n_years))
            for m, c in mes_counts.items()
        ]

    # Top scored — enrich with adjudicacion data
    df = df.copy()
    df["_score"] = df.apply(_simple_score, axis=1)
    top_scored_df = df.nlargest(30, "_score").copy()

    # Build best-adjudicacion lookup per licitacion
    adj_lookup: dict[str, dict[str, Any]] = {}
    if not adj_df.empty and "licitacion_id" in adj_df.columns:
        adj_for_scored = adj_df[adj_df["licitacion_id"].isin(top_scored_df["id_externo"])].copy()
        if not adj_for_scored.empty:
            adj_for_scored = adj_for_scored.sort_values("_importe", ascending=False)
            adj_for_scored = adj_for_scored.drop_duplicates(subset=["licitacion_id"], keep="first")
            for _, row in adj_for_scored.iterrows():
                lid = str(row["licitacion_id"])
                empresa = None
                if nombre_col in row.index:
                    empresa = str(row[nombre_col]) if pd.notna(row[nombre_col]) else None
                baja = (
                    float(row["baja_pct"])
                    if "baja_pct" in row.index and pd.notna(row.get("baja_pct"))
                    else None
                )
                fecha_adj = None
                if "fecha_adjudicacion" in row.index and pd.notna(row.get("fecha_adjudicacion")):
                    try:
                        fecha_adj = str(
                            pd.Timestamp(row["fecha_adjudicacion"]).strftime("%d/%m/%Y")
                        )
                    except Exception:
                        pass
                adj_lookup[lid] = {
                    "empresa": empresa,
                    "baja_pct": baja,
                    "fecha_adjudicacion": fecha_adj,
                }

    top_scored = []
    for _, row in top_scored_df.iterrows():
        eid = str(row.get("id_externo", ""))
        adj_info = adj_lookup.get(eid, {})
        score = float(row["_score"])
        estado_raw = (
            str(row["estado"]) if "estado" in row.index and pd.notna(row.get("estado")) else None
        )
        titulo_raw = (
            str(row["titulo"]) if "titulo" in row.index and pd.notna(row.get("titulo")) else None
        )
        tipo_contrato_raw = (
            str(row["tipo_contrato"])
            if "tipo_contrato" in row.index and pd.notna(row.get("tipo_contrato"))
            else None
        )
        cpv_raw = str(row["cpv"]) if "cpv" in row.index and pd.notna(row.get("cpv")) else None
        top_scored.append(
            TopScored(
                id_externo=eid,
                titulo=titulo_raw,
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                score=score,
                banda=_score_to_banda(score),
                ccaa=str(row["ccaa"])
                if "ccaa" in row.index and pd.notna(row.get("ccaa"))
                else None,
                estado=estado_raw,
                estado_desc=ESTADO_LABELS.get(estado_raw.strip(), estado_raw)
                if estado_raw
                else None,
                modulos_str=str(row["modulos_str"])
                if "modulos_str" in row.index and pd.notna(row.get("modulos_str"))
                else None,
                url=str(row["url"]) if "url" in row.index and pd.notna(row.get("url")) else None,
                tipo_proyecto=detect_project_type(titulo_raw) if titulo_raw else None,
                tipo_contrato_desc=tipo_contrato_label(tipo_contrato_raw)
                if tipo_contrato_raw
                else None,
                cpv_desc=cpv_label(cpv_raw) if cpv_raw else None,
                empresa=adj_info.get("empresa"),
                baja_pct=adj_info.get("baja_pct"),
                fecha_adjudicacion=adj_info.get("fecha_adjudicacion"),
            )
        )

    log.info("analytics_organo_detail_done", total=total)
    return OrganoDetailResult(
        kpis=kpis,
        top_adjudicatarios=top_adj,
        estacionalidad=estacionalidad,
        top_scored=top_scored,
    )
