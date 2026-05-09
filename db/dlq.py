"""Dead Letter Queue para extracciones fallidas.

Cada fallo de scraping (descarga, parseo, persistencia) se registra en
``failed_extractions`` en vez de perderse en los logs. Así se pueden reintentar
manualmente o investigar patrones de fallo.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)


def record_failure(
    run_id: str | None,
    fuente: str,
    error: BaseException,
    *,
    scope: str | None = None,
    payload_ref: str | None = None,
) -> None:
    """Persiste un fallo en la DLQ. No lanza excepciones — best-effort.

    Si ya existe un fallo no resuelto con el mismo (fuente, scope, payload_ref),
    incrementa ``retry_count`` y actualiza el mensaje en vez de insertar uno nuevo.
    Apoyado por el índice parcial ``idx_fail_unique_unresolved`` (migración 11).
    """
    error_type = type(error).__name__
    error_message = str(error)[:2000]
    now = now_utc_iso()
    try:
        with connect() as c:
            # Buscar fallo existente no resuelto con la misma clave lógica.
            # COALESCE garantiza que NULL == NULL para esta comparación.
            row = c.execute(
                "SELECT id FROM failed_extractions "
                "WHERE fuente = ? "
                "  AND COALESCE(scope, '') = COALESCE(?, '') "
                "  AND COALESCE(payload_ref, '') = COALESCE(?, '') "
                "  AND resolved_at IS NULL "
                "LIMIT 1",
                (fuente, scope, payload_ref),
            ).fetchone()
            if row is not None:
                c.execute(
                    "UPDATE failed_extractions SET "
                    "  retry_count = retry_count + 1, "
                    "  error_type = ?, "
                    "  error_message = ?, "
                    "  run_id = ?, "
                    "  created_at = ? "
                    "WHERE id = ?",
                    (error_type, error_message, run_id, now, row[0]),
                )
            else:
                c.execute(
                    "INSERT INTO failed_extractions "
                    "(run_id, fuente, scope, error_type, error_message, "
                    " payload_ref, retry_count, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 0, ?)",
                    (run_id, fuente, scope, error_type, error_message, payload_ref, now),
                )
    except Exception as e:
        log.warning("dlq_persist_failed", error=str(e), fuente=fuente)


def list_unresolved(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as c:
        cur = c.execute(
            "SELECT id, run_id, fuente, scope, error_type, error_message, "
            "retry_count, created_at "
            "FROM failed_extractions "
            "WHERE resolved_at IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def mark_resolved(failure_id: int) -> None:
    with connect() as c:
        c.execute(
            "UPDATE failed_extractions SET resolved_at = ? WHERE id = ?",
            (now_utc_iso(), failure_id),
        )


def increment_retry(failure_id: int) -> None:
    with connect() as c:
        c.execute(
            "UPDATE failed_extractions SET retry_count = retry_count + 1 WHERE id = ?",
            (failure_id,),
        )
