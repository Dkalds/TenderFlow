"""Servicio de extraction runs — historial del pipeline de scraping.

Centraliza las queries sobre ``extraction_runs`` usadas por las páginas
de calidad de datos y observabilidad, y ``record_run``, que envuelve un run
del pipeline y lo persiste al salir.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from db.repositories.extraction_runs import ExtractionRunRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = ExtractionRunRepository()


@dataclass
class RunMetrics:
    run_id: str
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    status: str = "running"  # running | ok | partial | error
    months_attempted: int = 0
    months_ok: int = 0
    months_failed: int = 0
    licitaciones_nuevas: int = 0
    licitaciones_actualizadas: int = 0
    adjudicaciones: int = 0
    errores_parseo: int = 0
    errores_descarga: int = 0
    notas: str = ""
    extras: dict[str, object] = field(default_factory=dict)


@contextmanager
def record_run(run_id: str) -> Iterator[RunMetrics]:
    """Context manager que persiste el resultado del run al salir."""
    t0 = time.monotonic()
    m = RunMetrics(run_id=run_id, started_at=datetime.now(UTC).isoformat())
    try:
        yield m
        if m.status == "running":
            m.status = "ok" if m.months_failed == 0 else "partial"
    except Exception:
        m.status = "error"
        raise
    finally:
        m.ended_at = datetime.now(UTC).isoformat()
        m.duration_ms = int((time.monotonic() - t0) * 1000)
        persist_run(
            run_id=m.run_id,
            started_at=m.started_at,
            ended_at=m.ended_at,
            duration_ms=m.duration_ms,
            status=m.status,
            months_attempted=m.months_attempted,
            months_ok=m.months_ok,
            months_failed=m.months_failed,
            licitaciones_nuevas=m.licitaciones_nuevas,
            licitaciones_actualizadas=m.licitaciones_actualizadas,
            adjudicaciones=m.adjudicaciones,
            errores_parseo=m.errores_parseo,
            errores_descarga=m.errores_descarga,
            notas=m.notas,
        )


def to_dict(m: RunMetrics) -> dict[str, object]:
    return asdict(m)


def load_runs(limit: int = 200) -> list[dict[str, Any]]:
    """Carga las últimas extraction runs (columnas completas para observabilidad)."""
    return _repo.load_runs(limit)


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
