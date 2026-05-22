"""Operational actions for Dead Letter Queue entries."""

from __future__ import annotations

from typing import Any

from db.dlq import get_failure, increment_retry, mark_resolved
from observability import bind_run_context, get_logger
from scheduler.dlq_retry import dispatch_retry

log = get_logger(__name__)


def retry_failure(failure_id: int) -> dict[str, Any]:
    """Reintenta un fallo DLQ conocido y lo resuelve si el retry termina OK."""
    failure = get_failure(failure_id)
    if failure is None:
        raise ValueError(f"DLQ failure not found: {failure_id}")
    if failure.get("resolved_at"):
        return {"status": "already_resolved", "failure_id": failure_id}
    if failure.get("exhausted_at"):
        return {"status": "exhausted", "failure_id": failure_id}

    fuente = str(failure.get("fuente") or "")
    scope = str(failure.get("scope") or "")
    run_id = bind_run_context(entrypoint="dlq_retry", failure_id=failure_id, fuente=fuente)

    try:
        ok = dispatch_retry(fuente, scope, run_id)
    except ValueError as exc:
        raise ValueError(f"Unsupported DLQ source for retry: {fuente}") from exc

    if ok:
        mark_resolved(failure_id)
    else:
        increment_retry(failure_id)
    log.info("dlq_retry_done", failure_id=failure_id, fuente=fuente, resolved=ok)
    return {"status": "resolved" if ok else "failed", "failure_id": failure_id}
