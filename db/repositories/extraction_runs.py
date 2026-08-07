"""Repository para extraction_runs — historial del pipeline de scraping."""

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


class ExtractionRunRepository:
    """Acceso a la tabla ``extraction_runs``."""

    def load_runs(self, limit: int = 200) -> list[dict[str, Any]]:
        """Carga las últimas extraction runs (columnas completas)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT " + _FULL_COLUMNS + " FROM extraction_runs "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
            return rows_to_dicts(cur)

    def load_calidad_runs(self, limit: int = 90) -> list[dict[str, Any]]:
        """Carga runs con columnas de calidad."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT " + _CALIDAD_COLUMNS + " FROM extraction_runs "
                "ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
            return rows_to_dicts(cur)

    def load_extracciones(self) -> list[dict[str, Any]]:
        """Carga el historial de extracciones (fecha, fuente, nuevas)."""
        with connect_read() as c:
            cur = c.execute("SELECT fecha, fuente, nuevas FROM extracciones ORDER BY fecha DESC")
            return rows_to_dicts(cur)

    def persist_run(
        self,
        *,
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

    def load_recent_daily_statuses(self, limit: int) -> list[str]:
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
            log.warning("recent_daily_statuses_load_failed", exc_info=True)
            return []
