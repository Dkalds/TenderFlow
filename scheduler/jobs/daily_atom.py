"""Daily ATOM ingestion + downstream canonical pipeline (ADR-012)."""

from __future__ import annotations

from observability.logging import get_logger

log = get_logger(__name__)


def run() -> None:
    """Execute the daily ATOM pipeline via the canonical pipeline_runs sequence."""
    from scheduler.pipeline_runs import run_daily_pipeline

    run_daily_pipeline()
