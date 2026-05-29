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


class PipelineResult(BaseModel):
    """Combined pipeline response."""

    upcoming: list[PipelineEntry] = Field(default_factory=list)
    total_en_plazo: int = 0
    vencen_7d: int = 0
    vencen_30d: int = 0


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

    # Sort by urgency and limit
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

    result = PipelineResult(
        upcoming=upcoming,
        total_en_plazo=total_en_plazo,
        vencen_7d=vencen_7d,
        vencen_30d=vencen_30d,
    )
    log.info("analytics_pipeline_done", total=total_en_plazo, vencen_7d=vencen_7d)
    return result
