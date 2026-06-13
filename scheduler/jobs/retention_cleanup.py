"""Data retention cleanup — purge historical rows per policy."""

from __future__ import annotations

from typing import Any


def run() -> dict[str, Any]:
    """Purge historical data according to the retention policy."""
    from scheduler.retention import run_retention

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
