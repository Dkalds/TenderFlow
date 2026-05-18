"""Servicio de extraction runs — historial del pipeline de scraping.

Centraliza las queries sobre ``extraction_runs`` usadas por las páginas
de calidad de datos y observabilidad.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read, init_db
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_FULL_COLUMNS = (
    "run_id, started_at, ended_at, duration_ms, status, "
    "months_attempted, months_ok, months_failed, "
    "licitaciones_nuevas, licitaciones_actualizadas, "
    "adjudicaciones, errores_parseo, errores_descarga, notas"
)

_CALIDAD_COLUMNS = (
    "started_at, status, errores_parseo, errores_descarga, "
    "months_attempted, months_ok, months_failed"
)


def load_runs(limit: int = 200) -> list[dict[str, Any]]:
    """Carga las últimas extraction runs (columnas completas para observabilidad)."""
    with connect_read() as c:
        cur = c.execute(
            f"SELECT {_FULL_COLUMNS} FROM extraction_runs "  # noqa: S608
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return rows_to_dicts(cur)


def load_calidad_runs(limit: int = 90) -> list[dict[str, Any]]:
    """Carga runs con columnas de calidad (subconjunto para calidad_datos)."""
    with connect_read() as c:
        cur = c.execute(
            f"SELECT {_CALIDAD_COLUMNS} FROM extraction_runs "  # noqa: S608
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        )
        return rows_to_dicts(cur)


def load_extracciones() -> list[dict[str, Any]]:
    """Carga el historial de extracciones (fecha, fuente, nuevas)."""
    with connect_read() as c:
        cur = c.execute("SELECT fecha, fuente, nuevas FROM extracciones ORDER BY fecha DESC")
        return rows_to_dicts(cur)


def persist_run(
    run_id: str,
    started_at: str,
    ended_at: str | None,
    duration_ms: int | None,
    status: str,
    months_attempted: int,
    months_ok: int,
    months_failed: int,
    licitaciones_nuevas: int,
    licitaciones_actualizadas: int,
    adjudicaciones: int,
    errores_parseo: int,
    errores_descarga: int,
    notas: str,
) -> None:
    """Persiste métricas de un run del pipeline en ``extraction_runs``."""
    try:
        init_db()
        with connect() as c:
            c.execute(
                "INSERT INTO extraction_runs "
                "(run_id, started_at, ended_at, duration_ms, status, "
                " months_attempted, months_ok, months_failed, "
                " licitaciones_nuevas, licitaciones_actualizadas, "
                " adjudicaciones, errores_parseo, errores_descarga, notas) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    started_at,
                    ended_at,
                    duration_ms,
                    status,
                    months_attempted,
                    months_ok,
                    months_failed,
                    licitaciones_nuevas,
                    licitaciones_actualizadas,
                    adjudicaciones,
                    errores_parseo,
                    errores_descarga,
                    notas,
                ),
            )
    except Exception as e:
        log.warning("run_metrics_persist_failed", error=str(e), run_id=run_id)


def load_recent_daily_statuses(limit: int) -> list[str]:
    """Carga los últimos ``limit`` estados de runs del carril diario."""
    try:
        with connect_read() as c:
            rows = c.execute(
                "SELECT status FROM extraction_runs "
                "WHERE notas LIKE 'daily|%' "
                "ORDER BY started_at DESC LIMIT ?",
                [limit],
            ).fetchall()
        return [r[0] for r in rows]
    except Exception:
        return []
