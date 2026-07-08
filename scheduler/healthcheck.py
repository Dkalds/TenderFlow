"""Healthcheck del pipeline.

Comprueba:
  1. La BD es accesible y tiene esquema correcto.
  2. Hubo al menos una extracción exitosa en las últimas N horas.
  3. No hay >K fallos sin resolver en la DLQ.

Salida:
  exit 0 → healthy
  exit 1 → warning (degraded)
  exit 2 → critical (unhealthy)

También imprime un JSON con el estado para consumirse vía dashboard o CI.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path when run as `python -m scheduler.healthcheck`
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from db.database import connect, init_db  # noqa: E402
from observability import AlertLevel, configure_logging, get_logger, notify  # noqa: E402

log = get_logger(__name__)


def run_check(freshness_hours: int = 36, dlq_threshold: int = 50) -> dict[str, Any]:
    init_db()
    status = "healthy"
    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    errors: list[str] = []
    info: dict[str, object] = {}

    # --- Métricas de infraestructura ---
    from config import settings

    db_path = settings.DB_PATH or (settings.DATA_DIR / "licitaciones.db")
    info["db_size_bytes"] = db_path.stat().st_size if db_path.exists() else 0
    data_dir = Path(settings.DATA_DIR)
    try:
        info["data_dir_free_bytes"] = shutil.disk_usage(data_dir).free
    except OSError:
        info["data_dir_free_bytes"] = None

    with connect() as c:
        t0 = time.monotonic()
        total = c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]
        info["last_query_ms"] = round((time.monotonic() - t0) * 1000, 2)
        info["licitaciones_total"] = int(total)
        checks.append({"name": "db_readable", "ok": True})

        last_run = c.execute(
            "SELECT run_id, started_at, status, months_ok, months_failed "
            "FROM extraction_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        run_ok = True
        if last_run is None:
            errors.append("sin_runs_registrados")
            run_ok = False
        else:
            info["last_run"] = {
                "run_id": last_run[0],
                "started_at": last_run[1],
                "status": last_run[2],
                "months_ok": last_run[3],
                "months_failed": last_run[4],
            }
            try:
                started = datetime.fromisoformat(last_run[1])
                if started.tzinfo is None:
                    started = started.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                started = datetime.now(UTC) - timedelta(days=365)
            age = datetime.now(UTC) - started
            info["last_run_age_hours"] = round(age.total_seconds() / 3600, 1)
            if age > timedelta(hours=freshness_hours):
                warnings.append(f"last_run_stale:{info['last_run_age_hours']}h")
                run_ok = False
            if last_run[2] == "error":
                errors.append(f"last_run_failed:{last_run[0]}")
                run_ok = False
        checks.append({"name": "last_run_fresh", "ok": run_ok})

        dlq_count = c.execute(
            "SELECT COUNT(*) FROM failed_extractions WHERE resolved_at IS NULL"
        ).fetchone()[0]
        info["dlq_unresolved"] = int(dlq_count)
        dlq_ok = dlq_count < dlq_threshold
        if not dlq_ok:
            warnings.append(f"dlq_above_threshold:{dlq_count}")
        checks.append({"name": "dlq_below_threshold", "ok": dlq_ok})

        # ── Plano de orquestación activo (ADR-012) ────────────────────
        import os

        active_plane = os.environ.get("SCHEDULER_PLANE", "unknown")
        info["active_plane"] = active_plane

        # Última pipeline canónica: timestamp del último KPI snapshot
        last_kpi = c.execute(
            "SELECT computed_at FROM kpi_snapshots ORDER BY computed_at DESC LIMIT 1"
        ).fetchone()
        info["last_pipeline_run"] = last_kpi[0] if last_kpi else None

        # Locks activos (ADR-012)
        try:
            now_iso = datetime.now(UTC).isoformat()
            active_locks = c.execute(
                "SELECT name, holder, expires_at FROM job_locks WHERE expires_at > ?",
                (now_iso,),
            ).fetchall()
            info["active_locks"] = [
                {"name": r[0], "holder": r[1], "expires_at": r[2]} for r in active_locks
            ]
        except Exception:
            info["active_locks"] = []

        # ── Tripwires de persistencia (ops_events, ADR-004) ───────────
        # Los counters Prometheus mueren con el proceso efimero del scheduler
        # (GH Actions). ops_events persiste en BD para que este healthcheck,
        # que SI corre en prod cada 6h, pueda leerlos.
        # Umbrales espejo de observability/alert_rules.yml.
        try:
            cutoff = (datetime.now(UTC) - timedelta(hours=6)).isoformat()
            rows = c.execute(
                "SELECT event_type, COUNT(*) FROM ops_events WHERE ts > ? GROUP BY event_type",
                (cutoff,),
            ).fetchall()
            ops_counts: dict[str, int] = {r[0]: int(r[1]) for r in rows}
            info["ops_events_6h"] = ops_counts

            # sqlite_busy: >=10 warn, >=60 error
            n_busy = ops_counts.get("sqlite_busy", 0)
            if n_busy >= 60:
                errors.append(f"sqlite_busy_critical:{n_busy}")
            elif n_busy >= 10:
                warnings.append(f"sqlite_busy_high:{n_busy}")
            checks.append({"name": "ops_events_busy", "ok": n_busy < 10})

            # write_slow: >=20 warn
            n_slow = ops_counts.get("write_slow", 0)
            if n_slow >= 20:
                warnings.append(f"write_slow_high:{n_slow}")
            checks.append({"name": "ops_events_write_slow", "ok": n_slow < 20})

            # writers_high: >=1 warn
            n_wh = ops_counts.get("writers_high", 0)
            if n_wh >= 1:
                warnings.append(f"writers_high:{n_wh}")
            checks.append({"name": "ops_events_writers_high", "ok": n_wh == 0})

            # Retención best-effort: eliminar eventos > 30 días
            try:
                retention_cutoff = (datetime.now(UTC) - timedelta(days=30)).isoformat()
                c.execute("DELETE FROM ops_events WHERE ts < ?", (retention_cutoff,))
            except Exception:
                pass

        except Exception as exc:
            exc_msg = str(exc).lower()
            if "no such table" in exc_msg or "no existe" in exc_msg:
                info["ops_events_missing"] = True
                checks.append({"name": "ops_events_busy", "ok": True})
                checks.append({"name": "ops_events_write_slow", "ok": True})
                checks.append({"name": "ops_events_writers_high", "ok": True})
            else:
                info["ops_events_error"] = str(exc)[:200]

    if errors:
        status = "critical"
    elif warnings:
        status = "degraded"

    return {
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
        "info": info,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--freshness-hours", type=int, default=36)
    p.add_argument("--dlq-threshold", type=int, default=50)
    p.add_argument("--alert", action="store_true", help="Emite alertas si el estado no es healthy")
    args = p.parse_args()

    configure_logging()
    result = run_check(args.freshness_hours, args.dlq_threshold)
    print(json.dumps(result, indent=2, default=str))

    if args.alert and result["status"] != "healthy":
        level = AlertLevel.CRITICAL if result["status"] == "critical" else AlertLevel.WARN
        notify(
            level,
            "Healthcheck tenderflow",
            body=f"Estado: {result['status']}",
            warnings=result["warnings"],
            errors=result["errors"],
            **{k: v for k, v in result["info"].items() if not isinstance(v, dict)},
        )

    if args.alert:
        # Alerts are sent via email; exit 0 so CI does not treat health status as a failure.
        return 0

    return {"healthy": 0, "degraded": 1, "critical": 2}.get(result["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
