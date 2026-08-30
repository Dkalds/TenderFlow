"""Data retention cleanup — purge historical rows per policy."""

from __future__ import annotations

from typing import Any


def run() -> dict[str, Any]:
    """Purge historical data according to the retention policy."""
    from scheduler.retention import SOLICITUDES_ACCESO_RETENTION_DAYS, run_retention

    return run_retention(
        runs_days=90,
        audit_days=180,
        dlq_days=30,
        history_days=365,
        access_days=180,
        idempotency_days=1,
        webhook_deliveries_days=90,
        # El único plazo de esta lista que además está publicado en el aviso
        # legal: sale de la constante, no de un literal, para que no pueda
        # separarse de lo que se le promete al visitante.
        solicitudes_acceso_days=SOLICITUDES_ACCESO_RETENTION_DAYS,
        apply=True,
    )
