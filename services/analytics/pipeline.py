"""Pipeline analytics — upcoming deadlines and alerts."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.analytics.scoring import score_dataframe
from services.licitaciones import load_stats_base_df

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class PipelineFilters(BaseModel):
    """Query filters for pipeline endpoint."""

    dias: int = 30
    limit: int = 50
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    q: str | None = None
    importe_min: float | None = None


class PipelineEntry(BaseModel):
    """Single pipeline entry with deadline info."""

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    fecha_limite: str | None = None
    dias_restantes: int
    estado: str | None = None
    score: int | None = None
    band: str | None = None


class HorizonteCount(BaseModel):
    """Count by horizon bucket."""

    horizonte: str
    count: int
    importe: float


class TrimestreCount(BaseModel):
    """Count by calendar quarter."""

    trimestre: str
    count: int
    importe: float


class UrgenciaValorPoint(BaseModel):
    """Scatter point: urgency vs value."""

    id_externo: str
    titulo: str | None = None
    dias_restantes: int
    importe: float
    es_urgente: bool


class PipelineResult(BaseModel):
    """Combined pipeline response."""

    upcoming: list[PipelineEntry] = Field(default_factory=list)
    total_en_plazo: int = 0
    vencen_7d: int = 0
    vencen_30d: int = 0
    # Dimensión económica del pipeline (suma de importe sobre el dataset completo
    # de la ventana, no solo los `limit` items devueltos). Antes el frontend no
    # tenía forma de mostrar "cuánto € hay en juego" sin re-derivarlo.
    valor_total: float = 0.0
    valor_7d: float = 0.0
    valor_30d: float = 0.0
    # Oportunidades con score de banda "Caliente" (≥75) dentro de la ventana
    # completa, no solo los `limit` items devueltos.
    calientes: int = 0
    valor_calientes: float = 0.0
    por_horizonte: list[HorizonteCount] = Field(default_factory=list)
    por_trimestre: list[TrimestreCount] = Field(default_factory=list)
    urgencia_valor: list[UrgenciaValorPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    df = load_stats_base_df()
    if not df.empty:
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
        if "fecha_publicacion" in df.columns:
            df["fecha_publicacion"] = pd.to_datetime(
                df["fecha_publicacion"], errors="coerce", utc=True
            )
        # Parse fecha_limite if present
        if "fecha_limite" in df.columns:
            df["fecha_limite_dt"] = pd.to_datetime(
                df["fecha_limite"],
                errors="coerce",
                utc=True,
            )
    return df


def _apply_filters(df: pd.DataFrame, filters: PipelineFilters) -> pd.DataFrame:
    """Aplica los filtros globales (misma semántica que overview._apply_filters)."""
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
    if filters.q:
        needle = filters.q.strip().lower()
        if needle:
            mask = (
                df["titulo"].fillna("").str.lower().str.contains(needle, regex=False)
                | df["organo_contratacion"].fillna("").str.lower().str.contains(needle, regex=False)
                | df["id_externo"].fillna("").str.lower().str.contains(needle, regex=False)
            )
            df = df[mask]
    if filters.importe_min is not None:
        df = df[df["importe"] >= filters.importe_min]
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_pipeline(filters: PipelineFilters) -> PipelineResult:
    """Compute upcoming deadlines and urgency alerts."""
    log.info("analytics_pipeline_start", dias=filters.dias, limit=filters.limit)
    df = _load_df()

    if df.empty or "fecha_limite_dt" not in df.columns:
        log.info("analytics_pipeline_done", total=0)
        return PipelineResult()

    # Dataset completo (pre-filtros de usuario) — contexto de percentiles/señales
    # para el scoring, igual que get_scoring: no se sesga por el subconjunto filtrado.
    base_df = df

    df = _apply_filters(df, filters)

    # Filter to future deadlines
    hoy = pd.Timestamp.now("UTC")
    df = df.dropna(subset=["fecha_limite_dt"])
    df = df[df["fecha_limite_dt"] > hoy]

    if df.empty:
        log.info("analytics_pipeline_done", total=0)
        return PipelineResult()

    # Calculate dias_restantes
    df = df.copy()
    df["dias_restantes"] = (df["fecha_limite_dt"] - hoy).dt.days

    # Filter within requested window
    df = df[df["dias_restantes"] <= filters.dias]

    # Counts
    total_en_plazo = len(df)
    vencen_7d = int((df["dias_restantes"] <= 7).sum())
    vencen_30d = int((df["dias_restantes"] <= 30).sum())

    # Valor económico (suma de importe) sobre la misma ventana que los conteos.
    _imp = pd.to_numeric(df["importe"], errors="coerce")
    valor_total = float(_imp.sum(skipna=True))
    valor_7d = float(_imp[df["dias_restantes"] <= 7].sum(skipna=True))
    valor_30d = float(_imp[df["dias_restantes"] <= 30].sum(skipna=True))

    # Sort by urgency and limit
    all_df = df.copy()  # keep full for extra computations

    # Score toda la ventana (no solo los `limit` items devueltos) para que el
    # conteo de "calientes" sea real sobre el dataset completo de la ventana.
    score_df = score_dataframe(base_df, all_df)
    if not score_df.empty:
        all_df["id_externo"] = all_df["id_externo"].astype(str)
        all_df = all_df.merge(score_df, on="id_externo", how="left")
    else:
        all_df["score"] = None
        all_df["band"] = None

    calientes_mask = all_df["band"] == "Caliente"
    calientes = int(calientes_mask.sum())
    valor_calientes = float(
        pd.to_numeric(all_df.loc[calientes_mask, "importe"], errors="coerce").sum(skipna=True)
    )

    df = all_df.sort_values("dias_restantes").head(filters.limit)

    upcoming = []
    for _, row in df.iterrows():
        upcoming.append(
            PipelineEntry(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                organo_contratacion=(
                    row.get("organo_contratacion")
                    if pd.notna(row.get("organo_contratacion"))
                    else None
                ),
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                fecha_limite=str(row.get("fecha_limite", "")) or None,
                dias_restantes=int(row["dias_restantes"]),
                estado=row.get("estado") if pd.notna(row.get("estado")) else None,
                score=int(row["score"]) if pd.notna(row.get("score")) else None,
                band=row.get("band") if pd.notna(row.get("band")) else None,
            )
        )

    # por_horizonte: [0,7), [7,30), [30,90), [90,∞)
    por_horizonte: list[HorizonteCount] = []
    if not all_df.empty:
        bins = [0, 7, 30, 90, float("inf")]
        labels = ["<7d", "7-30d", "30-90d", "90+d"]
        all_df["_horizonte"] = pd.cut(
            all_df["dias_restantes"], bins=bins, labels=labels, right=False
        )
        for label in labels:
            subset = all_df[all_df["_horizonte"] == label]
            por_horizonte.append(
                HorizonteCount(
                    horizonte=label,
                    count=len(subset),
                    importe=float(subset["importe"].sum(skipna=True)),
                )
            )

    # por_trimestre: group by quarter of fecha_limite
    por_trimestre: list[TrimestreCount] = []
    if not all_df.empty:
        all_df["_quarter"] = all_df["fecha_limite_dt"].dt.to_period("Q")
        q_grp = (
            all_df.dropna(subset=["_quarter"])
            .groupby("_quarter")
            .agg(_count=("id_externo", "count"), _importe=("importe", "sum"))
            .reset_index()
            .sort_values("_quarter")
        )
        for _, row in q_grp.iterrows():
            por_trimestre.append(
                TrimestreCount(
                    trimestre=str(row["_quarter"]),
                    count=int(row["_count"]),
                    importe=float(row["_importe"] or 0),
                )
            )

    # urgencia_valor: scatter (dias_restantes vs importe), max 200
    urgencia_valor: list[UrgenciaValorPoint] = []
    uv_df = all_df.dropna(subset=["importe"]).head(200)
    for _, row in uv_df.iterrows():
        urgencia_valor.append(
            UrgenciaValorPoint(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                dias_restantes=int(row["dias_restantes"]),
                importe=float(row["importe"]),
                es_urgente=int(row["dias_restantes"]) <= 7,
            )
        )

    result = PipelineResult(
        upcoming=upcoming,
        total_en_plazo=total_en_plazo,
        vencen_7d=vencen_7d,
        vencen_30d=vencen_30d,
        valor_total=valor_total,
        valor_7d=valor_7d,
        valor_30d=valor_30d,
        calientes=calientes,
        valor_calientes=valor_calientes,
        por_horizonte=por_horizonte,
        por_trimestre=por_trimestre,
        urgencia_valor=urgencia_valor,
    )
    log.info(
        "analytics_pipeline_done",
        total=total_en_plazo,
        vencen_7d=vencen_7d,
        calientes=calientes,
    )
    return result
