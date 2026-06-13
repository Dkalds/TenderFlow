"""Bulk refresh of recent months + downstream canonical pipeline (ADR-012)."""

from __future__ import annotations

import os

from observability.logging import get_logger

log = get_logger(__name__)


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
    """Refresh the last N months of data via the canonical pipeline_runs sequence."""
    from scheduler.pipeline_runs import run_bulk_pipeline

    months = _env_int("SCHEDULER_BULK_MONTHS", 3)
    run_bulk_pipeline(months)
