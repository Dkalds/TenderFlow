"""Tecnologias analytics — technology distribution."""

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


class TecnologiasFilters(BaseModel):
    """Query filters for tecnologias endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None


class TecnologiaEntry(BaseModel):
    """Single technology entry."""

    tecnologia: str
    count: int
    importe: float
    pct: float


class TecnologiasResult(BaseModel):
    """Combined tecnologias response."""

    tecnologias: list[TecnologiaEntry] = Field(default_factory=list)
    sin_clasificar: int = 0


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


def _apply_filters(df: pd.DataFrame, filters: TecnologiasFilters) -> pd.DataFrame:
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
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_tecnologias(filters: TecnologiasFilters) -> TecnologiasResult:
    """Compute technology distribution."""
    log.info("analytics_tecnologias_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        log.info("analytics_tecnologias_done", total=0)
        return TecnologiasResult()

    total = len(df)

    # Count unclassified
    sin_clasificar_mask = df["tecnologia"].isna() | (df["tecnologia"].astype(str).str.strip() == "")
    sin_clasificar = int(sin_clasificar_mask.sum())

    # Group classified records
    classified = df[~sin_clasificar_mask]
    if classified.empty:
        result = TecnologiasResult(sin_clasificar=sin_clasificar)
        log.info("analytics_tecnologias_done", total=0, sin_clasificar=sin_clasificar)
        return result

    g = (
        classified.groupby("tecnologia")
        .agg(count=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("count", ascending=False)
        .reset_index()
    )
    g["pct"] = g["count"] / total * 100

    tecnologias = [
        TecnologiaEntry(
            tecnologia=row["tecnologia"],
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
            pct=round(float(row["pct"]), 2),
        )
        for _, row in g.iterrows()
    ]

    result = TecnologiasResult(
        tecnologias=tecnologias,
        sin_clasificar=sin_clasificar,
    )
    log.info("analytics_tecnologias_done", total=len(tecnologias), sin_clasificar=sin_clasificar)
    return result
