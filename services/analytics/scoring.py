"""Opportunity scoring — puntuación 0-100 genérica para cualquier pliego.

Dimensiones (pesos configurables en ``settings.SCORING_WEIGHTS``, suman 100):

- **importe** (25): ratio P10-P90 del universo puntuable — el mercado abierto
  de hoy, no la tabla entera (ver ``load_importe_percentiles``). Sin importe →
  50% neutral + flag.
- **plazo** (15): escalones por días hasta vencimiento. Sin fecha → 50% neutral + flag.
- **competencia** (25): 1 - clamp((media_ofertas_CPV4-1)/9, 0, 1). Fallback a
  media global o neutral. Datos reales de adjudicaciones 24 meses.
- **margen** (20): 1 - min(baja_esperada/0.40, 1). Fuente: predicciones_baja.p50
  → fallback baja histórica CPV-4 → media global → neutral.
- **afinidad** (15, opcional): similitud semántica con el portfolio explícito
  (keywords, CPVs y referencias contractuales) usando embeddings en lote. Si
  no están disponibles, conserva el fallback determinista ``min(hits/3, 1)``
  y coincidencia CPV. Sin portfolio, el peso se redistribuye.
- **senal_tecnica** (10): fuerza de la evidencia de tecnología, como el máximo
  entre el score derivado del texto de los pliegos y la probabilidad del
  clasificador. Sin señal → 50% neutral + flag. Es genérica: puntúa la
  tecnología que el request filtra, sea cual sea, y no lleva keywords propias.
- **riesgo** (penalización pura, fuera de la suma): sin_importe -5, sin_titulo -3,
  sin_plazo -2. fuera_de_rango -15 (importe fuera del rango del perfil de usuario).

Feature B: ``get_scoring`` acepta ``user_key`` opcional → carga el perfil del
usuario y usa sus pesos/keywords/rango. Sin perfil → settings globales.

Universo puntuable (modo top-N): oportunidades **vivas** — estado no terminal y
plazo por vencer. El recorte y su medición están en
``AggregateRepository.scoring_candidates``; el modo page-aligned (``ids``) no lo
aplica, porque ahí manda el listado.

Total = suma dimensiones + riesgo, clamp [0, 100].
Bandas: ≥75 Caliente / ≥50 Atractiva / ≥25 Tibia / Descarte.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from config import settings
from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.analytics.affinity import build_portfolio, score_affinity_batch
from services.analytics.scoring_signals import (
    CompetenciaStats,
    ImportePercentiles,
    MargenStats,
    load_competencia_stats,
    load_importe_percentiles,
    load_margen_stats,
)

log = get_logger(__name__)

_repo = AggregateRepository()


# ---------------------------------------------------------------------------
# DTOs (shape estable: solo cambian las keys internas de ``desglose``)
# ---------------------------------------------------------------------------


class ScoringFilters(BaseModel):
    """Query filters for scoring."""

    min_score: int = 0
    limit: int = 50
    band: str | None = None
    # El filtro se aplica en SQL, sobre el universo puntuable, y no en el
    # cliente sobre el top-N ya cortado: el Radar filtraba el top-24 global por
    # `tecnologia` en el navegador, y como el corpus vivo tiene 13 licitaciones
    # SAP entre 1.643, la bandeja filtrada salía vacía mientras la cabecera
    # seguía prometiendo "top-24 de SAP" (ADR-014, invariante 1).
    tecnologia: str | None = None
    # Page-aligned mode: cuando viene, se puntúan EXACTAMENTE esas licitaciones
    # (las filas visibles del listado) y se ignoran min_score/band/limit. El
    # listado paginado/ordenado/filtrado decide qué ids; el scoring solo se alinea.
    ids: list[str] | None = None
    # Saca del ranking lo que el usuario ya descartó, ANTES de ordenar y cortar,
    # para que el top-N se rellene con las siguientes. Filtrarlas en el cliente
    # dejaba la bandeja vacía a quien triaba las 24: las descartadas seguían
    # ocupando su plaza en el corte. Opt-in: solo el Radar lo pide.
    exclude_dismissed: bool = False


class ScoredOpportunity(BaseModel):
    """Single scored opportunity."""

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    # Campos que pinta la tarjeta del Radar. Sin ellos, consumir este ranking
    # obligaba a rehidratar cada id contra el listado —y el único endpoint de
    # hidratación por ids exige API key, no sesión—, así que el Radar acababa
    # ordenando "las 24 abiertas más recientes" en vez del top-N del mercado.
    # Todos salen de `_SCORING_COLS`, que ya los seleccionaba salvo
    # `ml_tech_principal` (añadido a la proyección con este cambio).
    fecha_limite: str | None = None
    tecnologia: str | None = None
    fecha_publicacion: str | None = None
    cpv: str | None = None
    ccaa: str | None = None
    ml_tech_principal: str | None = None
    url: str | None = None
    # Fuente de ingesta de la licitación ('placsp', 'ted', 'pscp'…). Acompaña a
    # `url`: el inspector etiquetaba ese enlace como «Ver en PLACSP» para todas,
    # y con TED o PSCP apunta a otro portal.
    fuente: str | None = None
    estado: str | None = None
    score: int
    band: str
    risk_flags: list[str] = Field(default_factory=list)
    desglose: dict[str, float] = Field(default_factory=dict)


class ScoringSignalsHealth(BaseModel):
    """De qué estaba hecho el score de esta respuesta.

    Una señal caída y una señal sin datos producen el mismo resultado —todas
    las filas neutrales en esa dimensión— y hasta ahora eso no se distinguía
    de un score sano desde fuera: la señal de margen estuvo muerta semanas
    porque su query fallaba y el ``except`` devolvía stats vacías. Que el
    estado viaje con los datos es lo que convierte esa avería en algo visible
    en la UI en vez de en un ranking silenciosamente peor.
    """

    competencia: str = Field(description="ok | vacia | error")
    margen: str = Field(description="ok | vacia | error")
    percentiles_fuente: str = Field(description="universo_vivo | global | lote_local | sin_datos")
    afinidad_metodo: str = Field(
        description="semantic_embeddings | keyword_cpv_fallback | unavailable"
    )
    senal_tecnica: str = Field(default="ok", description="ok | error")

    @property
    def degradado(self) -> bool:
        """True si alguna señal no está aportando lo que debería."""
        return (
            self.competencia != "ok"
            or self.margen != "ok"
            or self.senal_tecnica != "ok"
            or self.percentiles_fuente != "universo_vivo"
        )


class ScoringResult(BaseModel):
    """Combined scoring response."""

    opportunities: list[ScoredOpportunity] = Field(default_factory=list)
    total_scored: int = Field(
        default=0,
        description=(
            "Oportunidades que pasaron los filtros, antes del truncado a `limit`. "
            "Puede ser mayor que len(opportunities)."
        ),
    )
    signals: ScoringSignalsHealth | None = None


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
    cpvs: list[str] | None = None
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
    affinity_scores: dict[str, float]
    affinity_method: str
    competencia_stats: CompetenciaStats
    margen_stats: MargenStats
    percentiles_fuente: str = "sin_datos"
    # Fuerza de la señal técnica por id. None = la consulta falló (todas las
    # filas quedan neutras y la salud lo reporta); {} = consultada y sin datos
    # (cada fila sin entrada lleva su propio flag).
    tech_signal: dict[str, float] | None = None
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

    Función pura (sin efectos secundarios). Conserva la suma original de
    ``weights`` — no un 100 literal: no puede asumir que le llegan validados,
    y un perfil con otra suma debe salir con esa misma suma en vez de con una
    escala inventada.

    El residuo del redondeo cae en la dimensión **mayor**, donde pesa menos en
    términos relativos. El orden de reparto es determinista incluso con empates
    (por peso descendente y, a igualdad, por nombre), para que dos requests con
    el mismo perfil no puedan devolver scores distintos.
    """
    if keywords or "afinidad" not in weights:
        return dict(weights)
    afinidad_peso = weights["afinidad"]
    resto = {k: v for k, v in weights.items() if k != "afinidad"}
    total_resto = sum(resto.values())
    if total_resto == 0:
        return dict(resto)

    objetivo = sum(weights.values())
    # De menor a mayor: el último en repartirse —y por tanto quien absorbe el
    # residuo— es el de más peso.
    items = sorted(resto.items(), key=lambda kv: (kv[1], kv[0]))
    result: dict[str, int] = {}
    acumulado = 0
    for i, (k, v) in enumerate(items):
        if i == len(items) - 1:
            result[k] = objetivo - acumulado
        else:
            extra = round(afinidad_peso * v / total_resto)
            result[k] = v + extra
            acumulado += v + extra
    return result


def _band(score: int) -> str:
    """Banda comercial de un score 0-100."""
    if score >= 75:
        return "Caliente"
    if score >= 50:
        return "Atractiva"
    if score >= 25:
        return "Tibia"
    return "Descarte"


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


def _load_tech_signal(df: pd.DataFrame, tecnologia: str | None) -> dict[str, float] | None:
    """Fuerza de la señal técnica por id, o None si la consulta falla."""
    if "id_externo" not in df.columns or df.empty:
        return {}
    ids = [str(value) for value in df["id_externo"].tolist()]
    try:
        return _repo.tech_signal_by_ids(ids, tecnologia=tecnologia)
    except Exception as exc:
        log.warning("scoring_signals_tecnica_error", error=str(exc))
        return None


def _build_context(
    df: pd.DataFrame,
    profile: ScoringProfile | None = None,
    *,
    importe_percentiles: ImportePercentiles | None = None,
    tecnologia: str | None = None,
) -> _ScoringContext:
    """Lee settings (o perfil de usuario) y carga señales para construir un contexto.

    Si se pasa un ``profile``, sus pesos y keywords tienen prioridad sobre settings.
    ``importe_percentiles`` permite inyectar los P10/P90 ya calculados en SQL
    sobre el universo puntuable (ADR-023) en vez de derivarlos del ``df``
    recibido — que tras la migración es una proyección acotada, no el dataset
    entero, y por tanto una referencia sesgada por los filtros del request.
    ``tecnologia`` (el filtro activo del request) decide de qué tecnología se
    mide la fuerza de la señal técnica.
    """
    if profile is not None and profile.weights:
        weights_raw = dict(profile.weights)
    else:
        weights_raw = dict(settings.SCORING_WEIGHTS)

    if profile is not None and profile.afinidad_keywords is not None:
        keywords = list(profile.afinidad_keywords)
    else:
        keywords = list(settings.SCORING_AFINIDAD_KEYWORDS)

    cpvs = list(profile.cpvs or []) if profile is not None else []
    # `contracts` sigue en `build_portfolio` para cuando haya de dónde sacarlos
    # (pursuits ganados), pero no se lee del perfil: la columna no existe, así
    # que `raw_profile.get("contracts")` era siempre None y la rama de
    # referencias contractuales, inalcanzable.
    portfolio = build_portfolio(keywords=keywords, cpvs=cpvs)
    eff_weights = _effective_weights(
        weights_raw,
        [*portfolio.keywords, *portfolio.cpvs, *portfolio.contracts],
    )
    affinity_batch = score_affinity_batch(df, portfolio)

    comp_stats = load_competencia_stats()
    margen_stats = load_margen_stats()

    if importe_percentiles is not None:
        imp_p10, imp_p90 = importe_percentiles.p10, importe_percentiles.p90
        percentiles_fuente = importe_percentiles.fuente
    else:
        valid_imp = (
            df["importe"].dropna() if "importe" in df.columns else pd.Series([], dtype=float)
        )
        imp_p10 = float(valid_imp.quantile(0.10)) if len(valid_imp) > 0 else 0.0
        imp_p90 = float(valid_imp.quantile(0.90)) if len(valid_imp) > 0 else 0.0
        percentiles_fuente = "lote_local" if len(valid_imp) > 0 else "sin_datos"

    # Solo se consulta si la dimensión pesa: un perfil legado sin la clave no
    # paga la query.
    tech_signal = (
        _load_tech_signal(df, tecnologia) if eff_weights.get("senal_tecnica", 0) > 0 else {}
    )

    return _ScoringContext(
        imp_p10=imp_p10,
        imp_p90=imp_p90,
        percentiles_fuente=percentiles_fuente,
        weights=eff_weights,
        keywords=keywords,
        affinity_scores=affinity_batch.scores,
        affinity_method=affinity_batch.method,
        competencia_stats=comp_stats,
        margen_stats=margen_stats,
        tech_signal=tech_signal,
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

    # 5. Afinidad — similitud semántica precalculada en lote; el servicio de
    # afinidad conserva el fallback histórico determinista si no hay embeddings.
    if ctx.affinity_scores and "afinidad" in w:
        fraccion_af = ctx.affinity_scores.get(id_externo, 0.0)
        d_afinidad = fraccion_af * w["afinidad"]
        desglose["afinidad"] = round(d_afinidad, 2)
    # Sin portfolio, la key se omite del desglose (peso ya redistribuido).

    # 6. Señal técnica — cuán confirmada está la tecnología en esta licitación,
    # según el texto de los pliegos y el clasificador. Hasta ahora esa señal
    # solo filtraba el universo: una licitación con SAP confirmado en el pliego
    # puntuaba exactamente igual que una sin ninguna evidencia.
    if w.get("senal_tecnica", 0) > 0:
        if ctx.tech_signal is None:
            # La consulta falló: neutral y sin flag por fila. No es un hueco de
            # esta licitación, y la salud de la respuesta ya lo reporta.
            d_tecnica = w["senal_tecnica"] * 0.5
        else:
            fuerza = ctx.tech_signal.get(id_externo)
            if fuerza is None:
                d_tecnica = w["senal_tecnica"] * 0.5
                flags.append("sin_senal_tecnica")
            else:
                d_tecnica = max(0.0, min(1.0, float(fuerza))) * w["senal_tecnica"]
        desglose["senal_tecnica"] = round(d_tecnica, 2)
    # Peso 0 o ausente (perfiles anteriores a la dimensión): key omitida, igual
    # que afinidad — una barra a cero en la UI se lee como "sin señal", que es
    # justo lo contrario de "no la estás puntuando".

    # 7. Riesgo — penalización pura (fuera de la suma, sin afectar datos de cobertura)
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

    return final, _band(final), flags, desglose


def score_dataframe(
    base_df: pd.DataFrame,
    target_df: pd.DataFrame,
    *,
    importe_percentiles: ImportePercentiles | None = None,
    tecnologia: str | None = None,
) -> pd.DataFrame:
    """Puntúa ``target_df`` con contexto (percentiles, señales) calculado sobre
    ``base_df``. Con ``importe_percentiles`` (los del universo puntuable,
    calculados en SQL — ADR-023), ``base_df`` puede ser una proyección acotada:
    la afinidad es por-fila, así que calcularla sobre el subconjunto equivale a
    calcularla sobre la tabla completa y consultar esos ids.

    Sin perfil de usuario: pensado para endpoints compartidos/cacheados donde
    el score no puede personalizarse por usuario (ver ``get_scoring`` para la
    variante personalizada). Requiere que ``target_df`` tenga las columnas que
    ``_score_row`` lee (``importe``, ``titulo``, ``cpv``, ``fecha_limite_dt``,
    ``id_externo``).

    Devuelve un DataFrame con columnas ``id_externo``, ``score``, ``band``.
    """
    if target_df.empty:
        return pd.DataFrame(columns=["id_externo", "score", "band"])

    ctx = _build_context(base_df, importe_percentiles=importe_percentiles, tecnologia=tecnologia)

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
    # ADR-023: proyección acotada desde SQL en vez de la tabla completa.
    # Sin `ids`, el universo puntuable son las oportunidades vivas: estado no
    # terminal Y plazo por vencer (ver `scoring_candidates`, que documenta por
    # qué el estado por sí solo no acotaba nada — el 91% de la tabla lo pasa).
    # En modo page-aligned (`ids`) se traen exactamente esas filas, cualquiera
    # sea su estado y su plazo, para no romper el alineado con el listado.
    if filters.ids:
        rows = _repo.licitaciones_by_ids([str(i) for i in filters.ids])
    else:
        rows = _repo.scoring_candidates(
            hoy_iso=pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
            filters=LicitacionesFilters(tecnologia=filters.tecnologia),
        )

    if not rows:
        log.info("analytics_scoring_done", total=0)
        return ScoringResult()

    df = pd.DataFrame(rows)
    df = df.assign(
        importe=pd.to_numeric(df["importe"], errors="coerce"),
        fecha_limite_dt=pd.to_datetime(df["fecha_limite"], errors="coerce", utc=True),
    )

    # Descartes: fuera del universo antes de ordenar, para que el top-N se
    # rellene con las siguientes. En modo page-aligned no aplica: ahí manda el
    # listado, y una fila que el usuario descartó sigue mereciendo su score.
    if filters.exclude_dismissed and user_key is not None and not filters.ids:
        try:
            from db import radar_dismissals

            descartadas = set(radar_dismissals.list_ids(user_key))
        except Exception as exc:
            log.warning("scoring_dismissals_load_error", error=str(exc))
            descartadas = set()
        if descartadas:
            df = df[~df["id_externo"].astype(str).isin(descartadas)]
            if df.empty:
                log.info("analytics_scoring_done", total=0, descartadas=len(descartadas))
                return ScoringResult()

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
                    cpvs=raw_profile.get("cpvs"),
                    importe_min=raw_profile.get("importe_min"),
                    importe_max=raw_profile.get("importe_max"),
                )
        except Exception as exc:
            log.warning("scoring_profile_load_error", error=str(exc))

    # Construir contexto inmutable (P10/P90 del universo vivo vía SQL cacheado
    # + señales + settings/perfil). Los percentiles se calculan en Postgres
    # sobre el mismo universo puntuable, no sobre la proyección acotada de este
    # request ni sobre la tabla entera.
    ctx = _build_context(
        df,
        profile=profile,
        importe_percentiles=load_importe_percentiles(),
        tecnologia=filters.tecnologia,
    )

    # Page-aligned mode: la restricción por ids ya viene aplicada desde SQL.
    # min_score/band/limit no aplican en este modo.
    id_filter = {str(i) for i in filters.ids} if filters.ids else None
    work = df

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
                # `pd.notna` es obligatorio: los NULL de Postgres llegan como
                # NaN de pandas, que Pydantic rechazaría contra `str | None`.
                fecha_limite=str(row["fecha_limite"])
                if pd.notna(row.get("fecha_limite"))
                else None,
                tecnologia=str(row["tecnologia"]) if pd.notna(row.get("tecnologia")) else None,
                fecha_publicacion=str(row["fecha_publicacion"])
                if pd.notna(row.get("fecha_publicacion"))
                else None,
                cpv=str(row["cpv"]) if pd.notna(row.get("cpv")) else None,
                ccaa=str(row["ccaa"]) if pd.notna(row.get("ccaa")) else None,
                ml_tech_principal=str(row["ml_tech_principal"])
                if pd.notna(row.get("ml_tech_principal"))
                else None,
                url=str(row["url"]) if pd.notna(row.get("url")) else None,
                fuente=str(row["fuente"]) if pd.notna(row.get("fuente")) else None,
                estado=str(row["estado"]) if pd.notna(row.get("estado")) else None,
                score=s,
                band=band,
                risk_flags=flags,
                desglose=desglose,
            )
        )

    # Se cuenta ANTES de truncar: `total_scored` es cuántas oportunidades
    # pasaron los filtros, no cuántas caben en la página. Con el conteo
    # posterior al corte, un `limit=24` siempre reportaba 24 y no había forma
    # de saber si detrás había 25 o 900.
    total = len(scored)
    if id_filter is None:
        scored.sort(key=lambda x: x.score, reverse=True)
        scored = scored[: filters.limit]

    result = ScoringResult(
        opportunities=scored,
        total_scored=total,
        signals=ScoringSignalsHealth(
            competencia=ctx.competencia_stats.status,
            margen=ctx.margen_stats.status,
            percentiles_fuente=ctx.percentiles_fuente,
            afinidad_metodo=ctx.affinity_method,
            senal_tecnica="error" if ctx.tech_signal is None else "ok",
        ),
    )
    log.info("analytics_scoring_done", total=total, devueltas=len(scored))
    return result
