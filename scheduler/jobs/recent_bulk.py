"""Bulk refresh of recent months + downstream KPI/aggregates/watchlist."""

from __future__ import annotations

import os


def _env_int(name: str, default: int, *, min_value: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(value, min_value)


def run() -> None:
    """Refresh the last N months of data and run downstream precomputations."""
    from scheduler.aggregates_precompute import run_aggregates_precompute
    from scheduler.kpi_precompute import run_kpi_precompute
    from scheduler.watchlist_alerts import check_and_notify
    from scraper.pipeline import update_recent

    months = _env_int("SCHEDULER_BULK_MONTHS", 3)
    results = update_recent(months)
    failed = [r for r in results if r.get("status") not in ("ok", "no_publicado")]
    if failed:
        raise RuntimeError(f"bulk refresh failed for {len(failed)} month(s): {failed}")
    run_kpi_precompute()
    run_aggregates_precompute()
    check_and_notify()
