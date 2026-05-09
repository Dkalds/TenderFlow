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
    from db.database import connect, init_db

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
                    m.run_id,
                    m.started_at,
                    m.ended_at,
                    m.duration_ms,
                    m.status,
                    m.months_attempted,
                    m.months_ok,
                    m.months_failed,
                    m.licitaciones_nuevas,
                    m.licitaciones_actualizadas,
                    m.adjudicaciones,
                    m.errores_parseo,
                    m.errores_descarga,
                    m.notas,
                ),
            )
    except Exception as e:
        log.warning("run_metrics_persist_failed", error=str(e), run_id=m.run_id)


def to_dict(m: RunMetrics) -> dict[str, object]:
    return asdict(m)
