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
    desglose: dict[str, float] = Field(default_factory=dict)


class ScoringResult(BaseModel):
    """Combined scoring response."""

    opportunities: list[ScoredOpportunity] = Field(default_factory=list)
    total_scored: int = 0


# ---------------------------------------------------------------------------
# Scoring logic (simplified from dashboard/stats/_base.py)
# ---------------------------------------------------------------------------

# Keywords that boost score — full 7-dimension scoring from dashboard/kpi_config.py
_SAP_SERVICES_PORTFOLIO = [
    "implementación",
    "implementacion",
    "migración",
    "migracion",
    "s/4hana",
    "s4hana",
    "rise",
    "mantenimiento",
    "soporte",
    "consultoría",
    "consultoria",
    "desarrollo",
    "integración",
    "integracion",
]

_S4HANA_KEYWORDS = ["s/4hana", "s4hana", "s/4 hana", "rise with sap"]

_SAP_MODULES = [
    "FI",
    "CO",
    "MM",
    "SD",
    "PP",
    "PM",
    "PS",
    "HCM",
    "FICO",
    "BW",
    "CRM",
    "SRM",
    "SCM",
    "GRC",
    "BASIS",
]

# Weights per dimension (total = 100)
_W_IMPORTE = 25
_W_PLAZO = 15
_W_MODULOS_SAP = 20
_W_PORTFOLIO_MATCH = 15
_W_S4HANA_BOOST = 10
_W_COMPETENCIA = 10
_W_RIESGO = 5


def _score_row(  # type: ignore[type-arg]
    row: pd.Series,
    imp_p10: float,
    imp_p90: float,
) -> tuple[int, str, list[str], dict[str, float]]:
    """Return (score 0-100, band, risk_flags, desglose) for a single row."""
    flags: list[str] = []
    desglose: dict[str, float] = {}

    # 1. Importe (0-25): normalize between P10-P90
    importe = row.get("importe")
    if pd.notna(importe) and imp_p90 > imp_p10:
        ratio = max(0.0, min(1.0, (float(importe) - imp_p10) / (imp_p90 - imp_p10)))
        d_importe = ratio * _W_IMPORTE
    elif pd.notna(importe):
        d_importe = _W_IMPORTE * 0.5
    else:
        d_importe = 0.0
        flags.append("sin_importe")
    desglose["importe"] = round(d_importe, 2)

    # 2. Plazo (0-15): 7-90 days to deadline = full points
    d_plazo = 0.0
    fecha_limite = row.get("fecha_limite_dt") if "fecha_limite_dt" in row.index else None
    if pd.notna(fecha_limite):
        days_left = (fecha_limite - pd.Timestamp.now("UTC")).days
        if 7 <= days_left <= 90:
            d_plazo = float(_W_PLAZO)
        elif 0 <= days_left < 7:
            d_plazo = float(_W_PLAZO) * 0.5
        elif 90 < days_left <= 180:
            d_plazo = float(_W_PLAZO) * 0.7
        elif days_left > 180:
            d_plazo = float(_W_PLAZO) * 0.3
    desglose["plazo"] = round(d_plazo, 2)

    # 3. Modulos SAP (0-20): count SAP module mentions, cap at 5
    titulo = str(row.get("titulo", "") or "").upper()
    titulo_lower = titulo.lower()
    module_count = sum(
        1
        for m in _SAP_MODULES
        if f" {m} " in f" {titulo} " or titulo.startswith(f"{m} ") or titulo.endswith(f" {m}")
    )
    module_count = min(module_count, 5)
    d_modulos = (module_count / 5) * _W_MODULOS_SAP
    desglose["modulos_sap"] = round(d_modulos, 2)

    # 4. Portfolio match (0-15): count keyword matches
    portfolio_count = sum(1 for kw in _SAP_SERVICES_PORTFOLIO if kw in titulo_lower)
    d_portfolio = min(portfolio_count / 3, 1.0) * _W_PORTFOLIO_MATCH
    desglose["portfolio_match"] = round(d_portfolio, 2)

    # 5. S/4HANA boost (0-10): binary
    d_s4hana = float(_W_S4HANA_BOOST) if any(kw in titulo_lower for kw in _S4HANA_KEYWORDS) else 0.0
    desglose["s4hana_boost"] = round(d_s4hana, 2)

    # 6. Competencia (0-10): placeholder — requires adjudicaciones history
    d_competencia = 0.0
    desglose["competencia"] = 0.0

    # 7. Riesgo (0 to -5): penalties
    d_riesgo = 0.0
    if "sin_importe" in flags:
        d_riesgo -= 5.0
    if not titulo_lower.strip():
        d_riesgo -= 3.0
        flags.append("sin_titulo")
    desglose["riesgo"] = round(d_riesgo, 2)

    total = d_importe + d_plazo + d_modulos + d_portfolio + d_s4hana + d_competencia + d_riesgo
    final = max(0, min(round(total), 100))

    if final >= 75:
        band = "Caliente"
    elif final >= 50:
        band = "Atractiva"
    elif final >= 25:
        band = "Tibia"
    else:
        band = "Descarte"

    return final, band, flags, desglose


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

    # Parse fecha_limite for plazo scoring
    if "fecha_limite" in df.columns:
        df["fecha_limite_dt"] = pd.to_datetime(df["fecha_limite"], errors="coerce", utc=True)

    # Compute P10/P90 for importe normalization
    valid_imp = df["importe"].dropna()
    imp_p10 = float(valid_imp.quantile(0.10)) if len(valid_imp) > 0 else 0.0
    imp_p90 = float(valid_imp.quantile(0.90)) if len(valid_imp) > 0 else 0.0

    scored: list[ScoredOpportunity] = []
    for _, row in df.iterrows():
        s, band, flags, desglose = _score_row(row, imp_p10, imp_p90)
        if s < filters.min_score:
            continue
        if filters.band and band != filters.band:
            continue
        scored.append(
            ScoredOpportunity(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                organo_contratacion=row.get("organo_contratacion")
                if pd.notna(row.get("organo_contratacion"))
                else None,
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                score=s,
                band=band,
                risk_flags=flags,
                desglose=desglose,
            )
        )

    scored.sort(key=lambda x: x.score, reverse=True)
    scored = scored[: filters.limit]

    result = ScoringResult(opportunities=scored, total_scored=len(scored))
    log.info("analytics_scoring_done", total=result.total_scored)
    return result
