"""Operational actions for Dead Letter Queue entries."""

from __future__ import annotations

import re
from typing import Any

from db.dlq import get_failure, increment_retry, mark_resolved
from observability import bind_run_context, get_logger
from scraper.pipeline import _DAILY_SOURCE, process_daily, process_month

log = get_logger(__name__)

_BULK_SOURCE_RE = re.compile(r"^bulk_(?P<year>\d{4})(?P<month>\d{2})$")


def retry_failure(failure_id: int) -> dict[str, Any]:
    """Reintenta un fallo DLQ conocido y lo resuelve si el retry termina OK."""
    failure = get_failure(failure_id)
    if failure is None:
        raise ValueError(f"DLQ failure not found: {failure_id}")
    if failure.get("resolved_at"):
        return {"status": "already_resolved", "failure_id": failure_id}

    fuente = str(failure.get("fuente") or "")
    run_id = bind_run_context(entrypoint="dlq_retry", failure_id=failure_id, fuente=fuente)

    bulk_match = _BULK_SOURCE_RE.match(fuente)
    if bulk_match:
        year = int(bulk_match.group("year"))
        month = int(bulk_match.group("month"))
        result = process_month(year, month, run_id=run_id, force=True)
    elif fuente == _DAILY_SOURCE:
        result = process_daily(run_id=run_id)
    else:
        raise ValueError(f"Unsupported DLQ source for retry: {fuente}")

    ok = result.get("status") in ("ok", "no_publicado")
    if ok:
        mark_resolved(failure_id)
    else:
        increment_retry(failure_id)
    log.info("dlq_retry_done", failure_id=failure_id, fuente=fuente, result=result, resolved=ok)
    return {"status": "resolved" if ok else "failed", "failure_id": failure_id, "result": result}
