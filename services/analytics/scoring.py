"""Opportunity scoring — 0-100 score combining commercial signals."""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ScoringFilters(BaseModel):
    """Query filters for scoring."""

    min_score: int = 0
    limit: int = 50
    band: str | None = None


class ScoredOpportunity(BaseModel):
    """Single scored opportunity."""

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    score: int
    band: str
    risk_flags: list[str] = Field(default_factory=list)


class ScoringResult(BaseModel):
    """Combined scoring response."""

    opportunities: list[ScoredOpportunity] = Field(default_factory=list)
    total_scored: int = 0


# ---------------------------------------------------------------------------
# Scoring logic (simplified from dashboard/stats/_base.py)
# ---------------------------------------------------------------------------

# Keywords that boost score — simplified portfolio match
_PORTFOLIO_KEYWORDS = [
    "software",
    "cloud",
    "digital",
    "datos",
    "ciberseguridad",
    "telecomunicaciones",
    "infraestructura",
    "consultor",
    "sap",
    "erp",
    "mantenimiento",
    "desarrollo",
    "sistema",
]


def _score_row(row: pd.Series, imp_max: float) -> tuple[int, str, list[str]]:  # type: ignore[type-arg]
    """Return (score 0-100, band, risk_flags) for a single row."""
    score = 0.0
    flags: list[str] = []

    # 1. Importe component (0-40 points): higher importe = higher score
    importe = row.get("importe")
    if pd.notna(importe) and imp_max > 0:
        score += (importe / imp_max) * 40
    else:
        flags.append("sin_importe")

    # 2. Title keyword match (0-30 points)
    titulo = str(row.get("titulo", "") or "").lower()
    if titulo:
        matches = sum(1 for kw in _PORTFOLIO_KEYWORDS if kw in titulo)
        score += min(matches * 10, 30)
    else:
        flags.append("sin_titulo")

    # 3. Recency (0-20 points): published in last 30 days gets full points
    fecha = row.get("fecha_publicacion")
    if pd.notna(fecha):
        days_ago = (pd.Timestamp.now("UTC") - fecha).days
        if days_ago <= 30:
            score += 20
        elif days_ago <= 90:
            score += 10
        elif days_ago <= 180:
            score += 5
    else:
        flags.append("sin_fecha")

    # 4. Estado bonus (0-10 points)
    estado = row.get("estado", "")
    if estado in ("PUB", "EV"):
        score += 10
    elif estado == "RES":
        score += 5

    final = min(round(score), 100)

    if final >= 70:
        band = "alta"
    elif final >= 40:
        band = "media"
    else:
        band = "baja"

    return final, band, flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_scoring(filters: ScoringFilters) -> ScoringResult:
    """Score all licitaciones and return filtered/sorted results."""
    log.info("analytics_scoring_start", filters=filters.model_dump(exclude_none=True))
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)

    if df.empty:
        log.info("analytics_scoring_done", total=0)
        return ScoringResult()

    df["fecha_publicacion"] = pd.to_datetime(
        df["fecha_publicacion"],
        errors="coerce",
        utc=True,
    )
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce")

    imp_max = float(df["importe"].max(skipna=True)) if df["importe"].notna().any() else 0.0

    scored: list[ScoredOpportunity] = []
    for _, row in df.iterrows():
        s, band, flags = _score_row(row, imp_max)
        if s < filters.min_score:
            continue
        if filters.band and band != filters.band:
            continue
        scored.append(
            ScoredOpportunity(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo"),
                organo_contratacion=row.get("organo_contratacion"),
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                score=s,
                band=band,
                risk_flags=flags,
            )
        )

    scored.sort(key=lambda x: x.score, reverse=True)
    scored = scored[: filters.limit]

    result = ScoringResult(opportunities=scored, total_scored=len(scored))
    log.info("analytics_scoring_done", total=result.total_scored)
    return result
