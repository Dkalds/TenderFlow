"""Pipeline analytics — upcoming deadlines and alerts."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class PipelineFilters(BaseModel):
    """Query filters for pipeline endpoint."""

    dias: int = 30
    limit: int = 50


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
    por_horizonte: list[HorizonteCount] = Field(default_factory=list)
    por_trimestre: list[TrimestreCount] = Field(default_factory=list)
    urgencia_valor: list[UrgenciaValorPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
        # Parse fecha_limite if present
        if "fecha_limite" in df.columns:
            df["fecha_limite_dt"] = pd.to_datetime(
                df["fecha_limite"],
                errors="coerce",
                utc=True,
            )
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
    df = df.sort_values("dias_restantes").head(filters.limit)

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
        por_horizonte=por_horizonte,
        por_trimestre=por_trimestre,
        urgencia_valor=urgencia_valor,
    )
    log.info("analytics_pipeline_done", total=total_en_plazo, vencen_7d=vencen_7d)
    return result
