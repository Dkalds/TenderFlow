"""Señales externas para el scoring de oportunidades.

Carga y cachea dos señales agregadas a partir de datos históricos reales:

- **CompetenciaStats**: media de ofertas recibidas por segmento CPV-4 en 24
  meses, más media global de fallback.
- **MargenStats**: p50 de baja esperada por licitación (desde ``predicciones_baja``),
  baja media histórica por CPV-4, y media global de fallback.

Los loaders siguen el patrón ``SignalAwareCache`` de services/licitaciones.py:
TTL + invalidación por señal de ingesta. En BD local sin datos históricos, las
stats quedan vacías y el scoring degrada a neutro + flag sin crash.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger
from services._data_cache import SignalAwareCache

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Dataclasses frozen (thread-safe, hashable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompetenciaStats:
    """Estadísticas de competencia por segmento CPV-4."""

    media_por_cpv4: dict[str, float] = field(default_factory=dict)
    media_global: float | None = None


@dataclass(frozen=True)
class MargenStats:
    """Estadísticas de margen / baja esperada."""

    # p50 de baja esperada por licitacion_id (de predicciones_baja)
    p50_por_licitacion: dict[str, float] = field(default_factory=dict)
    # baja media histórica por segmento CPV-4 (de adjudicaciones 24 meses)
    baja_media_por_cpv4: dict[str, float] = field(default_factory=dict)
    # baja media global (fallback de último recurso)
    baja_media_global: float | None = None


# ---------------------------------------------------------------------------
# Cachés con SignalAwareCache
# ---------------------------------------------------------------------------

_competencia_cache: SignalAwareCache[CompetenciaStats] = SignalAwareCache()
_margen_cache: SignalAwareCache[MargenStats] = SignalAwareCache()


def _cutoff_iso(months: int = 24) -> str:
    """ISO 8601 en UTC del instante hace ``months`` meses."""
    cutoff = datetime.now(tz=UTC) - timedelta(days=months * 30)
    return cutoff.isoformat()


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
              AND a.fecha_adjudicacion >= :cutoff
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
              AND a.fecha_adjudicacion >= :cutoff
              AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
            GROUP BY a.licitacion_id
        ) sub
    """
    try:
        with connect_read() as c:
            rows: list[dict[str, Any]] = rows_to_dicts(c.execute(sql, {"cutoff": cutoff}))
            media_por_cpv4 = {
                str(r["cpv4"]): float(r["media_ofertas"])
                for r in rows
                if r["cpv4"] is not None and r["media_ofertas"] is not None
            }
            row_global = c.execute(sql_global, {"cutoff": cutoff}).fetchone()
            media_global: float | None = None
            if row_global is not None:
                val = (
                    row_global[0] if not hasattr(row_global, "keys") else row_global["media_global"]
                )
                media_global = float(val) if val is not None else None
        return CompetenciaStats(media_por_cpv4=media_por_cpv4, media_global=media_global)
    except Exception as exc:
        log.warning("scoring_signals_competencia_error", error=str(exc))
        return CompetenciaStats()


def _load_margen_stats_raw(cutoff_months: int = 24) -> MargenStats:
    """Carga sin caché — llamado solo por SignalAwareCache.get()."""
    cutoff = _cutoff_iso(cutoff_months)
    # p50 de predicciones_baja (baja esperada normalizada 0-1)
    sql_pred = """
        SELECT licitacion_id, p50
        FROM predicciones_baja
    """
    # Baja media histórica por CPV-4 (de adjudicaciones 24 meses)
    # baja_pct = (1 - importe_adjudicado / importe_licitacion) * 100
    # Queremos fracción 0-1 para comparar con la fórmula del scoring
    sql_baja_cpv4 = """
        SELECT
            substr(l.cpv, 1, 4) AS cpv4,
            AVG(
                CASE
                    WHEN a.importe_licitacion > 0 AND a.importe_adjudicado IS NOT NULL
                    THEN (1.0 - a.importe_adjudicado / a.importe_licitacion)
                    ELSE NULL
                END
            ) AS baja_media
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE a.fecha_adjudicacion >= :cutoff
          AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
          AND l.cpv IS NOT NULL
          AND length(l.cpv) >= 4
          AND a.importe_licitacion > 0
          AND a.importe_adjudicado IS NOT NULL
        GROUP BY cpv4
        HAVING COUNT(*) >= 3
    """
    sql_baja_global = """
        SELECT AVG(
            CASE
                WHEN a.importe_licitacion > 0 AND a.importe_adjudicado IS NOT NULL
                THEN (1.0 - a.importe_adjudicado / a.importe_licitacion)
                ELSE NULL
            END
        ) AS baja_media_global
        FROM adjudicaciones a
        JOIN licitaciones l ON l.id_externo = a.licitacion_id
        WHERE a.fecha_adjudicacion >= :cutoff
          AND COALESCE(l.analysis_universe, 'technology_observed') = 'technology_observed'
          AND a.importe_licitacion > 0
          AND a.importe_adjudicado IS NOT NULL
    """
    try:
        with connect_read() as c:
            rows_pred: list[dict[str, Any]] = rows_to_dicts(c.execute(sql_pred))
            p50_por_licitacion = {
                str(r["licitacion_id"]): float(r["p50"])
                for r in rows_pred
                if r["licitacion_id"] is not None and r["p50"] is not None
            }
            rows_cpv4: list[dict[str, Any]] = rows_to_dicts(
                c.execute(sql_baja_cpv4, {"cutoff": cutoff})
            )
            baja_media_por_cpv4 = {
                str(r["cpv4"]): float(r["baja_media"])
                for r in rows_cpv4
                if r["cpv4"] is not None and r["baja_media"] is not None
            }
            row_global = c.execute(sql_baja_global, {"cutoff": cutoff}).fetchone()
            baja_media_global: float | None = None
            if row_global is not None:
                val = (
                    row_global[0]
                    if not hasattr(row_global, "keys")
                    else row_global["baja_media_global"]
                )
                baja_media_global = float(val) if val is not None else None
        return MargenStats(
            p50_por_licitacion=p50_por_licitacion,
            baja_media_por_cpv4=baja_media_por_cpv4,
            baja_media_global=baja_media_global,
        )
    except Exception as exc:
        log.warning("scoring_signals_margen_error", error=str(exc))
        return MargenStats()


# ---------------------------------------------------------------------------
# Public API — loaders con caché
# ---------------------------------------------------------------------------


def load_competencia_stats() -> CompetenciaStats:
    """Devuelve CompetenciaStats cacheadas (TTL + señal de ingesta)."""
    return _competencia_cache.get(_load_competencia_stats_raw)


def load_margen_stats() -> MargenStats:
    """Devuelve MargenStats cacheadas (TTL + señal de ingesta)."""
    return _margen_cache.get(_load_margen_stats_raw)


def clear_scoring_signals_cache() -> None:
    """Invalida ambas cachés de señales (para tests y post-ingesta)."""
    _competencia_cache.clear()
    _margen_cache.clear()
