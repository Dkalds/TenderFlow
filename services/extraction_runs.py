"""Servicio de extraction runs — historial del pipeline de scraping.

Centraliza las queries sobre ``extraction_runs`` usadas por las páginas
de calidad de datos y observabilidad.
"""

from __future__ import annotations

from typing import Any

from db.repositories.extraction_runs import ExtractionRunRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = ExtractionRunRepository()


def load_runs(limit: int = 200) -> list[dict[str, Any]]:
    """Carga las últimas extraction runs (columnas completas para observabilidad)."""
    return _repo.load_runs(limit)


def load_calidad_runs(limit: int = 90) -> list[dict[str, Any]]:
    """Carga runs con columnas de calidad (subconjunto para calidad_datos)."""
    return _repo.load_calidad_runs(limit)


def load_extracciones() -> list[dict[str, Any]]:
    """Carga el historial de extracciones (fecha, fuente, nuevas)."""
    return _repo.load_extracciones()


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
    _repo.persist_run(
        run_id=run_id,
        started_at=started_at,
        ended_at=ended_at,
        duration_ms=duration_ms,
        status=status,
        months_attempted=months_attempted,
        months_ok=months_ok,
        months_failed=months_failed,
        licitaciones_nuevas=licitaciones_nuevas,
        licitaciones_actualizadas=licitaciones_actualizadas,
        adjudicaciones=adjudicaciones,
        errores_parseo=errores_parseo,
        errores_descarga=errores_descarga,
        notas=notas,
    )


def load_recent_daily_statuses(limit: int) -> list[str]:
    """Carga los últimos ``limit`` estados de runs del carril diario."""
    return _repo.load_recent_daily_statuses(limit)
