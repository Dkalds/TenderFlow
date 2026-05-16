"""Long-running scheduler for Docker Compose deployments.

GitHub Actions remains the preferred production scheduler for Turso-backed
deployments. This loop is for local/self-hosted Docker stacks where Compose
should keep one service alive and run periodic jobs against the shared DB.
"""

from __future__ import annotations

import os
import signal
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from observability import AlertLevel, configure_logging, configure_tracing, get_logger, notify
from scheduler.anomaly_alerts import run_anomaly_checks
from scheduler.dlq_retry import retry_failed_extractions
from scheduler.drift_report import run_drift_report
from scheduler.kpi_precompute import run_kpi_precompute
from scheduler.watchlist_alerts import check_and_notify, send_pending_digests
from scraper.pipeline import update_daily, update_recent

log = get_logger(__name__)

# Evento global para shutdown graceful (se activa con SIGTERM/SIGINT)
_stop_event = threading.Event()


def _env_int(name: str, default: int, *, min_value: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("scheduler_loop_invalid_int", name=name, value=raw, default=default)
        return default
    return max(value, min_value)


def _run_job(name: str, fn: Callable[[], Any]) -> None:
    started = time.monotonic()
    try:
        result = fn()
        log.info(
            "scheduler_loop_job_done",
            job=name,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            result=result,
        )
    except Exception as exc:
        log.exception("scheduler_loop_job_failed", job=name)
        notify(AlertLevel.ERROR, f"Scheduler job fallo: {name}", body=str(exc))


def _run_daily_atom() -> None:
    result = update_daily()
    if result.get("status") != "ok":
        raise RuntimeError(f"daily atom failed: {result.get('status')}")
    run_kpi_precompute()
    check_and_notify()
    retry_failed_extractions()
    run_anomaly_checks()


def _run_recent_bulk(months: int) -> None:
    results = update_recent(months)
    failed = [r for r in results if r.get("status") not in ("ok", "no_publicado")]
    if failed:
        raise RuntimeError(f"bulk refresh failed for {len(failed)} month(s): {failed}")
    run_kpi_precompute()
    check_and_notify()


def _run_retention_cleanup() -> dict:
    """Purga datos históricos según la política de retención."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.retention_cleanup import run_retention

    return run_retention(
        runs_days=90,
        audit_days=180,
        dlq_days=30,
        history_days=365,
        access_days=180,
        idempotency_days=1,
        webhook_deliveries_days=90,
        apply=True,
    )


def main() -> int:
    configure_logging(json_logs=os.environ.get("LOG_FORMAT") == "json")
    configure_tracing()

    # Registrar handlers para shutdown graceful (SIGTERM de Docker, SIGINT de Ctrl+C)
    def _handle_signal(signum: int, frame: object) -> None:
        log.info("scheduler_loop_shutdown_signal", signal=signum)
        _stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    daily_interval = timedelta(minutes=_env_int("SCHEDULER_DAILY_INTERVAL_MINUTES", 240))
    bulk_interval = timedelta(minutes=_env_int("SCHEDULER_BULK_INTERVAL_MINUTES", 1440))
    bulk_months = _env_int("SCHEDULER_BULK_MONTHS", 3)
    dlq_interval = timedelta(minutes=_env_int("SCHEDULER_DLQ_RETRY_INTERVAL_MINUTES", 720))
    digest_interval = timedelta(minutes=_env_int("SCHEDULER_DIGEST_INTERVAL_MINUTES", 1440))
    anomaly_interval = timedelta(minutes=_env_int("SCHEDULER_ANOMALY_INTERVAL_MINUTES", 1440))
    drift_interval = timedelta(
        minutes=_env_int("SCHEDULER_DRIFT_INTERVAL_MINUTES", 10080)
    )  # weekly
    retention_interval = timedelta(hours=_env_int("SCHEDULER_RETENTION_INTERVAL_HOURS", 24))
    sleep_seconds = _env_int("SCHEDULER_POLL_SECONDS", 60)

    now = datetime.now(UTC)
    next_daily = now
    next_bulk = now
    next_dlq = now + timedelta(minutes=30)
    next_digest = now + timedelta(hours=1)
    next_anomaly = now + timedelta(hours=2)
    next_drift = now + timedelta(hours=6)  # primer drift report: 6h tras arranque
    next_retention = now + timedelta(hours=3)  # primer cleanup: 3h tras arranque
    log.info(
        "scheduler_loop_start",
        daily_interval_minutes=int(daily_interval.total_seconds() // 60),
        bulk_interval_minutes=int(bulk_interval.total_seconds() // 60),
        dlq_retry_interval_minutes=int(dlq_interval.total_seconds() // 60),
        digest_interval_minutes=int(digest_interval.total_seconds() // 60),
        anomaly_interval_minutes=int(anomaly_interval.total_seconds() // 60),
        drift_interval_minutes=int(drift_interval.total_seconds() // 60),
        retention_interval_hours=int(retention_interval.total_seconds() // 3600),
        bulk_months=bulk_months,
    )

    while True:
        now = datetime.now(UTC)
        if now >= next_daily:
            _run_job("daily_atom", _run_daily_atom)
            next_daily = datetime.now(UTC) + daily_interval
        if now >= next_bulk:
            _run_job("recent_bulk", lambda: _run_recent_bulk(bulk_months))
            next_bulk = datetime.now(UTC) + bulk_interval
        if now >= next_dlq:
            _run_job("dlq_retry", retry_failed_extractions)
            next_dlq = datetime.now(UTC) + dlq_interval
        if now >= next_digest:
            _run_job("digest_daily", lambda: send_pending_digests("daily"))
            next_digest = datetime.now(UTC) + digest_interval
        if now >= next_anomaly:
            _run_job("anomaly_checks", run_anomaly_checks)
            next_anomaly = datetime.now(UTC) + anomaly_interval
        if now >= next_drift:
            _run_job("drift_report", run_drift_report)
            next_drift = datetime.now(UTC) + drift_interval
        if now >= next_retention:
            _run_job("retention_cleanup", _run_retention_cleanup)
            next_retention = datetime.now(UTC) + retention_interval
        # Esperar el poll interval o despertar inmediatamente si llega señal de parada
        if _stop_event.wait(timeout=sleep_seconds):
            log.info("scheduler_loop_stopped_gracefully")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
