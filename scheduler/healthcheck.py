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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.database import connect, init_db
from observability import AlertLevel, configure_logging, get_logger, notify

log = get_logger(__name__)


def run_check(freshness_hours: int = 36, dlq_threshold: int = 50) -> dict:
    init_db()
    status = "healthy"
    checks: list[dict[str, object]] = []
    warnings: list[str] = []
    errors: list[str] = []
    info: dict[str, object] = {}

    # --- Métricas de infraestructura ---
    from config import settings

    db_path = Path(settings.DB_PATH)
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
            "Healthcheck licitaciones-sap",
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
