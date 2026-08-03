"""Organo detail analytics — drill-down for a single contracting body.

Consume proyecciones ACOTADAS al órgano pedido (ADR-023):
``AggregateRepository.licitaciones_por_organo`` (filtros globales en el
``WHERE``) y ``AdjudicacionRepository.load_por_organo``. Hasta 2026-08 cargaba
las dos tablas completas a pandas en el proceso API — bloqueado en Render por
el cortacircuitos full-table, que dejaba este endpoint vacío en producción.
El scoring simple, la estacionalidad y el lead-time siguen en pandas sobre el
subconjunto acotado. De paso viven dos campos que llegaban siempre nulos: la
identidad del adjudicatario usa el maestro canónico cuando existe (el código
prefería ``nombre_canonico``, pero el loader raw nunca lo traía) y
``baja_pct`` se calcula de ``importe_adjudicado``/``importe_licitacion`` (el
loader raw tampoco traía esa columna derivada).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.adjudicaciones import AdjudicacionRepository
from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.classification import (
    ESTADO_LABELS,
    cpv_label,
    detect_project_type,
    tipo_contrato_label,
)

log = get_logger(__name__)

_repo = AggregateRepository()
_adj_repo = AdjudicacionRepository()


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


def _to_repo_filters(filters: OrganoDetailFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
    )


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


def _adj_lookup_for(adj_df: pd.DataFrame, ids: pd.Series) -> dict[str, dict[str, Any]]:
    """Mejor adjudicación (mayor importe) por licitación de ``ids``."""
    lookup: dict[str, dict[str, Any]] = {}
    if adj_df.empty:
        return lookup
    sub = adj_df[adj_df["licitacion_id"].isin(ids)].copy()
    if sub.empty:
        return lookup
    sub = sub.sort_values("_importe", ascending=False)
    sub = sub.drop_duplicates(subset=["licitacion_id"], keep="first")
    for _, row in sub.iterrows():
        importe_lic = row.get("_importe_licitacion")
        importe_adj = row.get("_importe")
        baja = None
        if pd.notna(importe_adj) and pd.notna(importe_lic) and float(importe_lic) > 0:
            baja = float((1 - float(importe_adj) / float(importe_lic)) * 100)
        fecha_adj = None
        if pd.notna(row.get("fecha_adjudicacion")):
            try:
                fecha_adj = str(pd.Timestamp(row["fecha_adjudicacion"]).strftime("%d/%m/%Y"))
            except (ValueError, TypeError):
                pass
        lookup[str(row["licitacion_id"])] = {
            "empresa": str(row["nombre"]) if pd.notna(row.get("nombre")) else None,
            "baja_pct": baja,
            "fecha_adjudicacion": fecha_adj,
        }
    return lookup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_organo_detail(organo: str, filters: OrganoDetailFilters) -> OrganoDetailResult:
    """Drill-down for a single contracting body."""
    log.info("analytics_organo_detail_start", organo=organo)
    rows = _repo.licitaciones_por_organo(organo, _to_repo_filters(filters))
    if not rows:
        return OrganoDetailResult()

    df = pd.DataFrame(rows)
    df = df.assign(
        fecha_publicacion=pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True),
        importe=pd.to_numeric(df["importe"], errors="coerce"),
    )

    # KPIs
    total = len(df)
    importe_total = float(df["importe"].sum(skipna=True))
    notna_imp = int(df["importe"].notna().sum())
    importe_medio = float(importe_total / notna_imp) if notna_imp else 0.0
    adjudicado = len(df[df["estado"] == "ADJ"])
    pct_adj = (adjudicado / total * 100) if total else 0.0

    kpis = OrganoKpis(
        total_licitaciones=total,
        importe_total=importe_total,
        importe_medio=importe_medio,
        pct_adjudicado=pct_adj,
        lead_time_medio=None,
    )

    # Adjudicatarios del órgano (proyección acotada)
    adj_df = pd.DataFrame(_adj_repo.load_por_organo(organo))
    top_adj: list[TopAdjudicatario] = []
    if not adj_df.empty:
        adj_df = adj_df.assign(
            _importe=pd.to_numeric(adj_df["importe_adjudicado"], errors="coerce"),
            _importe_licitacion=pd.to_numeric(adj_df["importe_licitacion"], errors="coerce"),
        )
        g = (
            adj_df.groupby("nombre")
            .agg(count=("nombre", "count"), importe=("_importe", "sum"))
            .sort_values("count", ascending=False)
            .head(20)
            .reset_index()
        )
        top_adj = [
            TopAdjudicatario(
                nombre=str(row["nombre"]),
                count=int(row["count"]),
                importe=float(row["importe"] or 0),
            )
            for _, row in g.iterrows()
        ]

        # Lead time mediano (pub → adj) sobre las adjudicaciones del órgano
        kpis.lead_time_medio = _lead_time_median(adj_df)

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
    df = df.assign(_score=df.apply(_simple_score, axis=1))
    top_scored_df = df.nlargest(30, "_score").copy()
    adj_lookup = _adj_lookup_for(adj_df, top_scored_df["id_externo"])

    top_scored = []
    for _, row in top_scored_df.iterrows():
        eid = str(row.get("id_externo", ""))
        adj_info = adj_lookup.get(eid, {})
        score = float(row["_score"])
        estado_raw = str(row["estado"]) if pd.notna(row.get("estado")) else None
        titulo_raw = str(row["titulo"]) if pd.notna(row.get("titulo")) else None
        tipo_contrato_raw = (
            str(row["tipo_contrato"]) if pd.notna(row.get("tipo_contrato")) else None
        )
        cpv_raw = str(row["cpv"]) if pd.notna(row.get("cpv")) else None
        top_scored.append(
            TopScored(
                id_externo=eid,
                titulo=titulo_raw,
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                score=score,
                banda=_score_to_banda(score),
                ccaa=str(row["ccaa"]) if pd.notna(row.get("ccaa")) else None,
                estado=estado_raw,
                estado_desc=ESTADO_LABELS.get(estado_raw.strip(), estado_raw)
                if estado_raw
                else None,
                # La proyección de stats nunca trajo modulos_str (derivado del
                # loader enriquecido, sin uso aquí) — se preserva el None.
                modulos_str=None,
                url=str(row["url"]) if pd.notna(row.get("url")) else None,
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
