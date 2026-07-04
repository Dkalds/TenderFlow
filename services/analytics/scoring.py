"""Opportunity scoring — puntuación 0-100 genérica para cualquier pliego.

Dimensiones (pesos configurables en ``settings.SCORING_WEIGHTS``, suman 100):

- **importe** (25): ratio P10-P90 global. Sin importe → 50% neutral + flag.
- **plazo** (15): escalones por días hasta vencimiento. Sin fecha → 50% neutral + flag.
- **competencia** (25): 1 - clamp((media_ofertas_CPV4-1)/9, 0, 1). Fallback a
  media global o neutral. Datos reales de adjudicaciones 24 meses.
- **margen** (20): 1 - min(baja_esperada/0.40, 1). Fuente: predicciones_baja.p50
  → fallback baja histórica CPV-4 → media global → neutral.
- **afinidad** (15, opcional): min(hits/3, 1) sobre keywords configuradas en
  ``settings.SCORING_AFINIDAD_KEYWORDS``. Si la lista está vacía la key se omite
  del desglose y su peso se redistribuye proporcionalmente.
- **riesgo** (penalización pura, fuera de la suma): sin_importe -5, sin_titulo -3,
  sin_plazo -2. Los flags de cobertura de datos (sin_prediccion,
  sin_historico_competencia) NO penalizan.

Total = suma dimensiones + riesgo, clamp [0, 100].
Bandas: ≥75 Caliente / ≥50 Atractiva / ≥25 Tibia / Descarte.

Sin ninguna keyword de tecnología hardcodeada en este módulo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from config import settings
from observability.logging import get_logger
from services.analytics.scoring_signals import (
    CompetenciaStats,
    MargenStats,
    load_competencia_stats,
    load_margen_stats,
)
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs (shape estable: solo cambian las keys internas de ``desglose``)
# ---------------------------------------------------------------------------


class ScoringFilters(BaseModel):
    """Query filters for scoring."""

    min_score: int = 0
    limit: int = 50
    band: str | None = None
    # Page-aligned mode: cuando viene, se puntúan EXACTAMENTE esas licitaciones
    # (las filas visibles del listado) y se ignoran min_score/band/limit. El
    # listado paginado/ordenado/filtrado decide qué ids; el scoring solo se alinea.
    ids: list[str] | None = None


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
# Contexto inmutable por request (evita accesos globales en _score_row)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ScoringContext:
    """Parámetros globales del request de scoring."""

    imp_p10: float
    imp_p90: float
    # Pesos efectivos (ya redistribuidos si afinidad está vacía)
    weights: dict[str, int]
    keywords: list[str]
    competencia_stats: CompetenciaStats
    margen_stats: MargenStats
    now: pd.Timestamp = field(default_factory=lambda: pd.Timestamp.now("UTC"))


# ---------------------------------------------------------------------------
# Helpers puros
# ---------------------------------------------------------------------------


def _effective_weights(
    weights: dict[str, int],
    keywords: list[str],
) -> dict[str, int]:
    """Pesos efectivos: si no hay keywords, redistribuye el peso de afinidad.

    Función pura (sin efectos secundarios). Garantiza que la suma == 100.
    """
    if keywords or "afinidad" not in weights:
        return dict(weights)
    # Redistribuir el peso de afinidad proporcionalmente entre las demás dimensiones
    afinidad_peso = weights["afinidad"]
    resto = {k: v for k, v in weights.items() if k != "afinidad"}
    total_resto = sum(resto.values())
    if total_resto == 0:
        return dict(resto)
    # Distribución proporcional con corrección de redondeo en el mayor
    result: dict[str, int] = {}
    acumulado = 0
    items = sorted(resto.items(), key=lambda kv: kv[1], reverse=True)
    for i, (k, v) in enumerate(items):
        if i == len(items) - 1:
            result[k] = 100 - acumulado
        else:
            extra = round(afinidad_peso * v / total_resto)
            result[k] = v + extra
            acumulado += v + extra
    return result


def _cpv4(cpv: Any) -> str | None:
    """Extrae los primeros 4 dígitos de un CPV; None si es inválido."""
    if cpv is None or (isinstance(cpv, float) and pd.isna(cpv)):
        return None
    s = str(cpv).strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return None


# ---------------------------------------------------------------------------
# Construcción del contexto (separa la lectura de settings del cómputo puro)
# ---------------------------------------------------------------------------


def _build_context(df: pd.DataFrame) -> _ScoringContext:
    """Lee settings y carga señales para construir un _ScoringContext inmutable.

    Importa los loaders por nombre de módulo para que los tests puedan hacer
    ``patch.object`` sobre el módulo scoring_signals directamente.
    """
    weights_raw = dict(settings.SCORING_WEIGHTS)
    keywords = list(settings.SCORING_AFINIDAD_KEYWORDS)
    eff_weights = _effective_weights(weights_raw, keywords)

    comp_stats = load_competencia_stats()
    margen_stats = load_margen_stats()

    valid_imp = df["importe"].dropna() if "importe" in df.columns else pd.Series([], dtype=float)
    imp_p10 = float(valid_imp.quantile(0.10)) if len(valid_imp) > 0 else 0.0
    imp_p90 = float(valid_imp.quantile(0.90)) if len(valid_imp) > 0 else 0.0

    return _ScoringContext(
        imp_p10=imp_p10,
        imp_p90=imp_p90,
        weights=eff_weights,
        keywords=keywords,
        competencia_stats=comp_stats,
        margen_stats=margen_stats,
    )


# ---------------------------------------------------------------------------
# Scoring por fila
# ---------------------------------------------------------------------------


def _score_row(
    row: pd.Series,
    ctx: _ScoringContext,
) -> tuple[int, str, list[str], dict[str, float]]:
    """Devuelve (score 0-100, band, risk_flags, desglose) para una fila."""
    flags: list[str] = []
    desglose: dict[str, float] = {}
    w = ctx.weights

    # 1. Importe — sin importe → 50% neutral + flag (penaliza en riesgo, no aquí)
    importe = row.get("importe")
    if pd.notna(importe) and ctx.imp_p90 > ctx.imp_p10:
        ratio = max(0.0, min(1.0, (float(importe) - ctx.imp_p10) / (ctx.imp_p90 - ctx.imp_p10)))
        d_importe = ratio * w.get("importe", 0)
    elif pd.notna(importe):
        d_importe = w.get("importe", 0) * 0.5
    else:
        d_importe = w.get("importe", 0) * 0.5  # neutral, no 0
        flags.append("sin_importe")
    desglose["importe"] = round(d_importe, 2)

    # 2. Plazo — sin fecha → 50% neutral + flag
    titulo = str(row.get("titulo", "") or "")
    titulo_lower = titulo.casefold()

    d_plazo = 0.0
    fecha_limite = row.get("fecha_limite_dt") if "fecha_limite_dt" in row.index else None
    if pd.notna(fecha_limite) and fecha_limite is not None:
        days_left = (fecha_limite - ctx.now).days
        if 7 <= days_left <= 90:
            d_plazo = float(w.get("plazo", 0))
        elif 0 <= days_left < 7:
            d_plazo = float(w.get("plazo", 0)) * 0.5
        elif 90 < days_left <= 180:
            d_plazo = float(w.get("plazo", 0)) * 0.7
        elif days_left > 180:
            d_plazo = float(w.get("plazo", 0)) * 0.3
        # days_left < 0: vencido → 0.0
    else:
        d_plazo = w.get("plazo", 0) * 0.5  # neutral
        flags.append("sin_plazo")
    desglose["plazo"] = round(d_plazo, 2)

    # 3. Competencia — media de ofertas por CPV-4 en 24 meses
    cpv4 = _cpv4(row.get("cpv"))
    media_ofertas: float | None = None
    if cpv4 is not None:
        media_ofertas = ctx.competencia_stats.media_por_cpv4.get(cpv4)
    if media_ofertas is None:
        media_ofertas = ctx.competencia_stats.media_global

    if media_ofertas is not None:
        # 1 oferta media = 100% (sin competencia), ≥10 = 0%
        fraccion = 1.0 - max(0.0, min(1.0, (media_ofertas - 1.0) / 9.0))
        d_competencia = fraccion * w.get("competencia", 0)
    else:
        d_competencia = w.get("competencia", 0) * 0.5  # neutral
        flags.append("sin_historico_competencia")
    desglose["competencia"] = round(d_competencia, 2)

    # 4. Margen — baja esperada (baja esperada ≥40% = guerra de precios = 0)
    id_externo = str(row.get("id_externo", ""))
    baja: float | None = ctx.margen_stats.p50_por_licitacion.get(id_externo)
    if baja is None and cpv4 is not None:
        baja = ctx.margen_stats.baja_media_por_cpv4.get(cpv4)
    if baja is None:
        baja = ctx.margen_stats.baja_media_global

    if baja is not None:
        fraccion_margen = 1.0 - min(baja / 0.40, 1.0)
        d_margen = fraccion_margen * w.get("margen", 0)
    else:
        d_margen = w.get("margen", 0) * 0.5  # neutral
        flags.append("sin_prediccion")
    desglose["margen"] = round(d_margen, 2)

    # 5. Afinidad — solo si hay keywords configuradas (y su peso está activo)
    if ctx.keywords and "afinidad" in w:
        hits = sum(1 for kw in ctx.keywords if kw.casefold() in titulo_lower)
        fraccion_af = min(hits / 3, 1.0)
        d_afinidad = fraccion_af * w["afinidad"]
        desglose["afinidad"] = round(d_afinidad, 2)
    # Si no hay keywords, la key "afinidad" se omite del desglose (peso ya redistribuido)

    # 6. Riesgo — penalización pura (fuera de la suma, sin afectar datos de cobertura)
    d_riesgo = 0.0
    if "sin_importe" in flags:
        d_riesgo -= 5.0
    if not titulo_lower.strip():
        d_riesgo -= 3.0
        flags.append("sin_titulo")
    if "sin_plazo" in flags:
        d_riesgo -= 2.0
    desglose["riesgo"] = round(d_riesgo, 2)

    # Total: suma de dimensiones (excepto riesgo) + riesgo
    dim_sum = sum(v for k, v in desglose.items() if k != "riesgo")
    total = dim_sum + d_riesgo
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
    """Puntúa licitaciones y devuelve resultados filtrados/ordenados."""
    log.info("analytics_scoring_start", filters=filters.model_dump(exclude_none=True))
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)

    if df.empty:
        log.info("analytics_scoring_done", total=0)
        return ScoringResult()

    if "fecha_publicacion" in df.columns:
        df["fecha_publicacion"] = pd.to_datetime(
            df["fecha_publicacion"],
            errors="coerce",
            utc=True,
        )
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce")

    # Parse fecha_limite para la dimensión de plazo
    if "fecha_limite" in df.columns:
        df["fecha_limite_dt"] = pd.to_datetime(df["fecha_limite"], errors="coerce", utc=True)

    # Construir contexto inmutable (P10/P90 globales + señales + settings)
    ctx = _build_context(df)

    # Page-aligned mode: restringir a los ids pedidos antes de iterar.
    # min_score/band/limit no aplican en este modo.
    id_filter = {str(i) for i in filters.ids} if filters.ids else None
    work = df
    if id_filter is not None:
        work = (
            df[df["id_externo"].astype(str).isin(id_filter)]
            if "id_externo" in df.columns
            else df.iloc[0:0]
        )

    scored: list[ScoredOpportunity] = []
    for _, row in work.iterrows():
        s, band, flags, desglose = _score_row(row, ctx)
        if id_filter is None:
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

    if id_filter is None:
        scored.sort(key=lambda x: x.score, reverse=True)
        scored = scored[: filters.limit]

    result = ScoringResult(opportunities=scored, total_scored=len(scored))
    log.info("analytics_scoring_done", total=result.total_scored)
    return result
