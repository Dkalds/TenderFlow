"""Señales externas para el scoring de oportunidades.

Carga y cachea tres señales agregadas a partir de datos reales:

- **CompetenciaStats**: media de ofertas recibidas por segmento CPV-4 en 24
  meses, más media global de fallback.
- **MargenStats**: p50 de baja esperada por licitación (desde ``predicciones_baja``),
  baja media histórica por CPV-4, y media global de fallback.
- **ImportePercentiles**: P10/P90 de importe del universo puntuable, que es la
  referencia contra la que normaliza la dimensión ``importe``.

Los loaders siguen el patrón ``SignalAwareCache`` de services/licitaciones.py:
TTL + invalidación por señal de ingesta. En BD local sin datos históricos, las
stats quedan vacías y el scoring degrada a neutro + flag sin crash.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from db.database import connect_read
from db.repositories.aggregates import AggregateRepository
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger
from services._data_cache import SignalAwareCache
from services.sql_fragments import BAJA_PCT_SQL, TECHNOLOGY_OBSERVED_SQL, VALID_PAIR_LOTE

log = get_logger(__name__)

_repo = AggregateRepository()

# ---------------------------------------------------------------------------
# Dataclasses frozen (thread-safe, hashable)
# ---------------------------------------------------------------------------


# Estados posibles de una señal. ``vacia`` y ``error`` producen exactamente el
# mismo score —todo neutral— pero significan cosas opuestas: en un caso la BD
# no tiene esa historia todavía, en el otro la consulta se rompió. No
# distinguirlos es lo que dejó la señal de margen muerta durante semanas sin
# que nadie lo notara (ver la nota de ``a.importe_licitacion`` más abajo).
SIGNAL_OK = "ok"
SIGNAL_VACIA = "vacia"
SIGNAL_ERROR = "error"


@dataclass(frozen=True)
class CompetenciaStats:
    """Estadísticas de competencia por segmento CPV-4."""

    media_por_cpv4: dict[str, float] = field(default_factory=dict)
    media_global: float | None = None
    status: str = SIGNAL_VACIA


@dataclass(frozen=True)
class MargenStats:
    """Estadísticas de margen / baja esperada."""

    # p50 de baja esperada por licitacion_id (de predicciones_baja)
    p50_por_licitacion: dict[str, float] = field(default_factory=dict)
    # baja media histórica por segmento CPV-4 (de adjudicaciones 24 meses)
    baja_media_por_cpv4: dict[str, float] = field(default_factory=dict)
    # baja media global (fallback de último recurso)
    baja_media_global: float | None = None
    status: str = SIGNAL_VACIA


@dataclass(frozen=True)
class ImportePercentiles:
    """P10/P90 de importe y de qué población salen.

    ``fuente`` distingue los tres desenlaces posibles, y se propaga a la
    respuesta del endpoint: un score calculado contra la distribución global
    (fallback) no significa lo mismo que uno calculado contra el mercado vivo,
    y quien lea el número merece saber cuál de los dos está mirando.
    """

    p10: float = 0.0
    p90: float = 0.0
    fuente: str = "sin_datos"  # universo_vivo | global | sin_datos


# ---------------------------------------------------------------------------
# Cachés con SignalAwareCache
# ---------------------------------------------------------------------------

_competencia_cache: SignalAwareCache[CompetenciaStats] = SignalAwareCache()
_margen_cache: SignalAwareCache[MargenStats] = SignalAwareCache()
_percentiles_cache: SignalAwareCache[ImportePercentiles] = SignalAwareCache()

# Por debajo de este número de importes, los percentiles del universo vivo son
# ruido muestral y se prefiere la distribución global, que es estable.
_MIN_IMPORTES_UNIVERSO = 50


def _months_ago(months: int, *, now: datetime | None = None) -> datetime:
    """Instante de hace ``months`` meses de calendario.

    Aritmética de calendario y no ``timedelta(days=months * 30)``: con 30 días
    por mes, la ventana "24 meses" duraba en realidad 720 días y se comía casi
    un mes de historia de adjudicaciones sin que nada lo dijera.

    ``now`` se inyecta en los tests (mismo motivo que el ``hoy_iso`` de
    ``scoring_candidates``: el resultado no depende del reloj de quien lo corre).
    """
    ahora = now if now is not None else datetime.now(tz=UTC)
    total = ahora.year * 12 + (ahora.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(ahora.day, monthrange(year, month)[1])
    return ahora.replace(year=year, month=month, day=day)


def _cutoff_iso(months: int = 24) -> str:
    """ISO 8601 en UTC del instante hace ``months`` meses."""
    return _months_ago(months).isoformat()


def _load_competencia_stats_raw(cutoff_months: int = 24) -> CompetenciaStats:
    """Carga sin caché — llamado solo por SignalAwareCache.get()."""
    cutoff = _cutoff_iso(cutoff_months)
    # Sub-select por licitacion_id para no sobre-ponderar multi-lote (una licitación
    # puede tener múltiples adjudicaciones; tomamos la máx de ofertas por licitación).
    sql = """
        SELECT
            substr(l.cpv, 1, 4)      AS cpv4,
            AVG(sub.max_ofertas)      AS media_ofertas
        FROM (
            SELECT
                a.licitacion_id,
                MAX(a.n_ofertas_recibidas) AS max_ofertas
            FROM adjudicaciones a
            WHERE a.n_ofertas_recibidas IS NOT NULL
              AND a.fecha_adjudicacion >= %s
            GROUP BY a.licitacion_id
        ) sub
        JOIN licitaciones l ON l.id_externo = sub.licitacion_id
        WHERE l.cpv IS NOT NULL
          AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
          AND length(l.cpv) >= 4
        GROUP BY cpv4
        HAVING COUNT(*) >= 3
    """
    sql_global = """
        SELECT AVG(sub.max_ofertas) AS media_global
        FROM (
            SELECT
                a.licitacion_id,
                MAX(a.n_ofertas_recibidas) AS max_ofertas
            FROM adjudicaciones a
            JOIN licitaciones l ON l.id_externo = a.licitacion_id
            WHERE a.n_ofertas_recibidas IS NOT NULL
              AND a.fecha_adjudicacion >= %s
              AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
            GROUP BY a.licitacion_id
        ) sub
    """
    try:
        with connect_read() as c:
            rows: list[dict[str, Any]] = rows_to_dicts(c.execute(sql, (cutoff,)))
            media_por_cpv4 = {
                str(r["cpv4"]): float(r["media_ofertas"])
                for r in rows
                if r["cpv4"] is not None and r["media_ofertas"] is not None
            }
            row_global = c.execute(sql_global, (cutoff,)).fetchone()
            media_global: float | None = None
            if row_global is not None:
                val = (
                    row_global[0] if not hasattr(row_global, "keys") else row_global["media_global"]
                )
                media_global = float(val) if val is not None else None
        hay_datos = bool(media_por_cpv4) or media_global is not None
        return CompetenciaStats(
            media_por_cpv4=media_por_cpv4,
            media_global=media_global,
            status=SIGNAL_OK if hay_datos else SIGNAL_VACIA,
        )
    except Exception as exc:
        log.warning("scoring_signals_competencia_error", error=str(exc))
        return CompetenciaStats(status=SIGNAL_ERROR)


def _load_margen_stats_raw(cutoff_months: int = 24) -> MargenStats:
    """Carga sin caché — llamado solo por SignalAwareCache.get()."""
    cutoff = _cutoff_iso(cutoff_months)
    # p50 de predicciones_baja (baja esperada normalizada 0-1). Sin WHERE a
    # propósito: el job de ML solo predice licitaciones abiertas (5 k por
    # corrida), pero el upsert no purga, así que la tabla acumula filas de
    # expedientes ya cerrados — y esos los sigue puntuando el modo page-aligned
    # del Detalle, que no recorta por estado ni por plazo. Un JOIN de higiene
    # contra el universo vivo le quitaría el margen a esas filas en silencio.
    # Si el conteo que loguea este loader crece más allá de ~200 k, la salida
    # es purgar por antigüedad en el job de ML, no filtrar aquí.
    sql_pred = """
        SELECT licitacion_id, p50
        FROM predicciones_baja
    """
    # Baja media histórica por CPV-4 (de adjudicaciones 24 meses), como
    # fracción 0-1 para comparar con la fórmula del scoring. El denominador es
    # el presupuesto real de cada fila de adjudicación (el de su lote si lo
    # tiene, v65_lotes) vía EFFECTIVE_BUDGET_SQL dentro de BAJA_PCT_SQL: la
    # comparación es por fila, no agregada por licitación, así que usar
    # ``l.importe`` sobreestimaría la baja de cualquier expediente multi-lote
    # (mismo patrón que services/ml/scoring.py). La columna ``a.importe_licitacion``
    # que se usaba antes no existe en el esquema: la query fallaba entera y el
    # ``except`` devolvía stats vacías, dejando la señal de margen muerta.
    sql_baja_cpv4 = f"""
        SELECT
            substr(l.cpv, 1, 4) AS cpv4,
            AVG({BAJA_PCT_SQL} / 100) AS baja_media
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN lotes lo ON lo.id = a.lote_id
        WHERE a.fecha_adjudicacion >= %s
          AND {TECHNOLOGY_OBSERVED_SQL}
          AND l.cpv IS NOT NULL
          AND length(l.cpv) >= 4
          AND {VALID_PAIR_LOTE}
        GROUP BY cpv4
        HAVING COUNT(*) >= 3
    """  # noqa: S608 — BAJA_PCT_SQL/VALID_PAIR_LOTE/TECHNOLOGY_OBSERVED_SQL son fragmentos constantes; el valor va con ?
    sql_baja_global = f"""
        SELECT AVG({BAJA_PCT_SQL} / 100) AS baja_media_global
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        LEFT JOIN lotes lo ON lo.id = a.lote_id
        WHERE a.fecha_adjudicacion >= %s
          AND {TECHNOLOGY_OBSERVED_SQL}
          AND {VALID_PAIR_LOTE}
    """  # noqa: S608 — fragmentos constantes; el valor va con ?
    try:
        with connect_read() as c:
            rows_pred: list[dict[str, Any]] = rows_to_dicts(c.execute(sql_pred))
            p50_por_licitacion = {
                str(r["licitacion_id"]): float(r["p50"])
                for r in rows_pred
                if r["licitacion_id"] is not None and r["p50"] is not None
            }
            rows_cpv4: list[dict[str, Any]] = rows_to_dicts(c.execute(sql_baja_cpv4, (cutoff,)))
            baja_media_por_cpv4 = {
                str(r["cpv4"]): float(r["baja_media"])
                for r in rows_cpv4
                if r["cpv4"] is not None and r["baja_media"] is not None
            }
            row_global = c.execute(sql_baja_global, (cutoff,)).fetchone()
            baja_media_global: float | None = None
            if row_global is not None:
                val = (
                    row_global[0]
                    if not hasattr(row_global, "keys")
                    else row_global["baja_media_global"]
                )
                baja_media_global = float(val) if val is not None else None
        log.info("scoring_signals_margen_cargada", predicciones=len(p50_por_licitacion))
        hay_datos = (
            bool(p50_por_licitacion) or bool(baja_media_por_cpv4) or baja_media_global is not None
        )
        return MargenStats(
            p50_por_licitacion=p50_por_licitacion,
            baja_media_por_cpv4=baja_media_por_cpv4,
            baja_media_global=baja_media_global,
            status=SIGNAL_OK if hay_datos else SIGNAL_VACIA,
        )
    except Exception as exc:
        log.warning("scoring_signals_margen_error", error=str(exc))
        return MargenStats(status=SIGNAL_ERROR)


def _load_importe_percentiles_raw() -> ImportePercentiles:
    """Carga sin caché — llamado solo por SignalAwareCache.get()."""
    hoy_iso = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    try:
        p10, p90, n = _repo.importe_percentiles_universo(hoy_iso=hoy_iso)
        if n >= _MIN_IMPORTES_UNIVERSO:
            return ImportePercentiles(p10=p10, p90=p90, fuente="universo_vivo")
        log.info("scoring_percentiles_fallback_global", importes_universo=n)
        g10, g90 = _repo.importe_percentiles()
        if g90 > g10:
            return ImportePercentiles(p10=g10, p90=g90, fuente="global")
        return ImportePercentiles()
    except Exception as exc:
        log.warning("scoring_signals_percentiles_error", error=str(exc))
        return ImportePercentiles()


# ---------------------------------------------------------------------------
# Public API — loaders con caché
# ---------------------------------------------------------------------------


def load_competencia_stats() -> CompetenciaStats:
    """Devuelve CompetenciaStats cacheadas (TTL + señal de ingesta)."""
    return _competencia_cache.get(_load_competencia_stats_raw)


def load_margen_stats() -> MargenStats:
    """Devuelve MargenStats cacheadas (TTL + señal de ingesta)."""
    return _margen_cache.get(_load_margen_stats_raw)


def load_importe_percentiles() -> ImportePercentiles:
    """Devuelve los percentiles de importe cacheados (TTL + señal de ingesta).

    La caché es lo que saca del camino caliente los 7,4 s que costaba
    ``importe_percentiles()`` —seq scan y sort de 1,63 M importes— en **cada**
    request de scoring, incluidos los del Radar.
    """
    return _percentiles_cache.get(_load_importe_percentiles_raw)


def clear_scoring_signals_cache() -> None:
    """Invalida las tres cachés de señales (para tests y post-ingesta)."""
    _competencia_cache.clear()
    _margen_cache.clear()
    _percentiles_cache.clear()
