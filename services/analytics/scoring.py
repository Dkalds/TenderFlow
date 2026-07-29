"""Opportunity scoring — puntuación 0-100 genérica para cualquier pliego.

Dimensiones (pesos configurables en ``settings.SCORING_WEIGHTS``, suman 100):

- **importe** (25): ratio P10-P90 global. Sin importe → 50% neutral + flag.
- **plazo** (15): escalones por días hasta vencimiento. Sin fecha → 50% neutral + flag.
- **competencia** (25): 1 - clamp((media_ofertas_CPV4-1)/9, 0, 1). Fallback a
  media global o neutral. Datos reales de adjudicaciones 24 meses.
- **margen** (20): 1 - min(baja_esperada/0.40, 1). Fuente: predicciones_baja.p50
  → fallback baja histórica CPV-4 → media global → neutral.
- **afinidad** (15, opcional): min(hits/3, 1) sobre keywords configuradas en
  ``settings.SCORING_AFINIDAD_KEYWORDS`` o en el perfil del usuario.
  Si la lista está vacía la key se omite del desglose y su peso se redistribuye.
- **riesgo** (penalización pura, fuera de la suma): sin_importe -5, sin_titulo -3,
  sin_plazo -2. fuera_de_rango -15 (importe fuera del rango del perfil de usuario).

Feature B: ``get_scoring`` acepta ``user_key`` opcional → carga el perfil del
usuario y usa sus pesos/keywords/rango. Sin perfil → settings globales.

Total = suma dimensiones + riesgo, clamp [0, 100].
Bandas: ≥75 Caliente / ≥50 Atractiva / ≥25 Tibia / Descarte.
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
from services.licitaciones import load_stats_base_df

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
class ScoringProfile:
    """Perfil de usuario para scoring personalizado (Feature B).

    Cuando es None, se usan los settings globales.
    """

    weights: dict[str, int] | None = None
    afinidad_keywords: list[str] | None = None
    importe_min: float | None = None
    importe_max: float | None = None


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
    # Rango de importe del perfil de usuario (None = sin restricción)
    importe_min: float | None = None
    importe_max: float | None = None
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


def _build_context(df: pd.DataFrame, profile: ScoringProfile | None = None) -> _ScoringContext:
    """Lee settings (o perfil de usuario) y carga señales para construir un contexto.

    Si se pasa un ``profile``, sus pesos y keywords tienen prioridad sobre settings.
    """
    if profile is not None and profile.weights:
        weights_raw = dict(profile.weights)
    else:
        weights_raw = dict(settings.SCORING_WEIGHTS)

    if profile is not None and profile.afinidad_keywords is not None:
        keywords = list(profile.afinidad_keywords)
    else:
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
        importe_min=profile.importe_min if profile else None,
        importe_max=profile.importe_max if profile else None,
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

    # Penalización por importe fuera del rango del perfil de usuario (Feature B)
    importe_val = row.get("importe")
    if pd.notna(importe_val) and (ctx.importe_min is not None or ctx.importe_max is not None):
        imp_float = float(importe_val)
        fuera_de_rango = (ctx.importe_min is not None and imp_float < ctx.importe_min) or (
            ctx.importe_max is not None and imp_float > ctx.importe_max
        )
        if fuera_de_rango:
            d_riesgo -= 15.0
            flags.append("fuera_de_rango")

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


def score_dataframe(base_df: pd.DataFrame, target_df: pd.DataFrame) -> pd.DataFrame:
    """Puntúa ``target_df`` con contexto (percentiles, señales) calculado sobre
    ``base_df`` (el dataset completo, para que P10/P90 y medias no se sesguen
    por un subconjunto ya filtrado).

    Sin perfil de usuario: pensado para endpoints compartidos/cacheados donde
    el score no puede personalizarse por usuario (ver ``get_scoring`` para la
    variante personalizada). Requiere que ``target_df`` tenga las columnas que
    ``_score_row`` lee (``importe``, ``titulo``, ``cpv``, ``fecha_limite_dt``,
    ``id_externo``).

    Devuelve un DataFrame con columnas ``id_externo``, ``score``, ``band``.
    """
    if target_df.empty:
        return pd.DataFrame(columns=["id_externo", "score", "band"])

    ctx = _build_context(base_df)

    ids: list[str] = []
    scores: list[int] = []
    bands: list[str] = []
    for _, row in target_df.iterrows():
        s, band, _flags, _desglose = _score_row(row, ctx)
        ids.append(str(row.get("id_externo", "")))
        scores.append(s)
        bands.append(band)

    return pd.DataFrame({"id_externo": ids, "score": scores, "band": bands})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_scoring(
    filters: ScoringFilters,
    user_key: str | None = None,
) -> ScoringResult:
    """Puntúa licitaciones y devuelve resultados filtrados/ordenados.

    Si ``user_key`` se pasa, carga el perfil del usuario y aplica sus pesos/keywords.
    Sin perfil, usa los settings globales (comportamiento anterior).
    """
    log.info(
        "analytics_scoring_start",
        filters=filters.model_dump(exclude_none=True),
        personalized=user_key is not None,
    )
    df = load_stats_base_df()

    if df.empty:
        log.info("analytics_scoring_done", total=0)
        return ScoringResult()

    # Parse fecha_limite para la dimensión de plazo. Usa assign() en vez de
    # asignación in-place: load_stats_base_df() devuelve el DataFrame
    # cacheado compartido (sin .copy()), así que mutar una columna aquí
    # contaminaría la caché entre requests concurrentes.
    if "fecha_limite" in df.columns:
        df = df.assign(
            fecha_limite_dt=pd.to_datetime(df["fecha_limite"], errors="coerce", utc=True)
        )

    # Cargar perfil del usuario si se proporciona
    profile: ScoringProfile | None = None
    if user_key is not None:
        try:
            from db.repositories.user_profiles import get_user_profile

            raw_profile = get_user_profile(user_key)
            if raw_profile is not None:
                profile = ScoringProfile(
                    weights=raw_profile.get("weights"),
                    afinidad_keywords=raw_profile.get("afinidad_keywords"),
                    importe_min=raw_profile.get("importe_min"),
                    importe_max=raw_profile.get("importe_max"),
                )
        except Exception as exc:
            log.warning("scoring_profile_load_error", error=str(exc))

    # Construir contexto inmutable (P10/P90 globales + señales + settings/perfil)
    ctx = _build_context(df, profile=profile)

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
