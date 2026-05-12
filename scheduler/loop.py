"""Long-running scheduler for Docker Compose deployments.

GitHub Actions remains the preferred production scheduler for Turso-backed
deployments. This loop is for local/self-hosted Docker stacks where Compose
should keep one service alive and run periodic jobs against the shared DB.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from observability import AlertLevel, configure_logging, get_logger, notify
from scheduler.kpi_precompute import run_kpi_precompute
from scheduler.watchlist_alerts import check_and_notify
from scraper.pipeline import update_daily, update_recent

log = get_logger(__name__)


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


def _run_recent_bulk(months: int) -> None:
    results = update_recent(months)
    failed = [r for r in results if r.get("status") not in ("ok", "no_publicado")]
    if failed:
        raise RuntimeError(f"bulk refresh failed for {len(failed)} month(s): {failed}")
    run_kpi_precompute()
    check_and_notify()


def main() -> int:
    configure_logging(json_logs=os.environ.get("LOG_FORMAT") == "json")

    daily_interval = timedelta(minutes=_env_int("SCHEDULER_DAILY_INTERVAL_MINUTES", 240))
    bulk_interval = timedelta(minutes=_env_int("SCHEDULER_BULK_INTERVAL_MINUTES", 1440))
    bulk_months = _env_int("SCHEDULER_BULK_MONTHS", 3)
    sleep_seconds = _env_int("SCHEDULER_POLL_SECONDS", 60)

    now = datetime.now(UTC)
    next_daily = now
    next_bulk = now
    log.info(
        "scheduler_loop_start",
        daily_interval_minutes=int(daily_interval.total_seconds() // 60),
        bulk_interval_minutes=int(bulk_interval.total_seconds() // 60),
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
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
