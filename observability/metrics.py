"""Métricas por run del pipeline — persistidas en BD para visualizar histórico."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from observability.logging import get_logger

log = get_logger(__name__)


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
        _persist(m)


def _persist(m: RunMetrics) -> None:
    from services.extraction_runs import persist_run

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
