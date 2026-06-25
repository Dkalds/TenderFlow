"""Dead Letter Queue para extracciones fallidas.

Cada fallo de scraping (descarga, parseo, persistencia) se registra en
``failed_extractions`` en vez de perderse en los logs. Así se pueden reintentar
manualmente o investigar patrones de fallo.

Columnas clave:
- ``created_at``     — timestamp de la primera ocurrencia (immutable).
- ``last_attempt_at``— timestamp del último intento (se actualiza en cada retry).
  Usado por el motor de backoff en ``dlq_retry.py``.
- ``exhausted_at``   — timestamp en que se marcó como agotada (retry_count >= max).
  NULL mientras sigue siendo candidata a retry.
- ``resolved_at``    — timestamp de resolución exitosa.
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
    incrementa ``retry_count``, actualiza el mensaje y registra ``last_attempt_at``.
    ``created_at`` permanece immutable (timestamp de la primera ocurrencia).
    Apoyado por el índice parcial ``idx_fail_unique_unresolved`` (migración 11).
    """
    error_type = type(error).__name__
    error_message = str(error)[:2000]
    now = now_utc_iso()
    try:
        with connect() as c:
            row = c.execute(
                "SELECT id FROM failed_extractions "
                "WHERE fuente = ? "
                "  AND COALESCE(scope, '') = COALESCE(?, '') "
                "  AND COALESCE(payload_ref, '') = COALESCE(?, '') "
                "  AND resolved_at IS NULL "
                "  AND exhausted_at IS NULL "
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
                    "  last_attempt_at = ? "
                    "WHERE id = ?",
                    (error_type, error_message, run_id, now, row[0]),
                )
            else:
                c.execute(
                    "INSERT INTO failed_extractions "
                    "(run_id, fuente, scope, error_type, error_message, "
                    " payload_ref, retry_count, created_at, last_attempt_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (run_id, fuente, scope, error_type, error_message, payload_ref, now, now),
                )
    except Exception as e:
        log.warning("dlq_persist_failed", error=str(e), fuente=fuente)


def list_unresolved(limit: int = 100) -> list[dict[str, Any]]:
    """Devuelve fallos abiertos (no resueltos y no agotados)."""
    with connect() as c:
        cur = c.execute(
            "SELECT id, run_id, fuente, scope, error_type, error_message, "
            "retry_count, created_at, last_attempt_at "
            "FROM failed_extractions "
            "WHERE resolved_at IS NULL AND exhausted_at IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def count_unresolved() -> int:
    """Número de fallos abiertos (no resueltos y no agotados) en la DLQ.

    Misma condición que :func:`list_unresolved`, pero un ``COUNT(*)`` barato:
    lo usa el panel de Calidad de Datos para no infracontar la pérdida real.
    """
    with connect() as c:
        row = c.execute(
            "SELECT COUNT(*) FROM failed_extractions "
            "WHERE resolved_at IS NULL AND exhausted_at IS NULL"
        ).fetchone()
        return int(row[0]) if row else 0


def list_exhausted(limit: int = 100) -> list[dict[str, Any]]:
    """Devuelve fallos agotados (retry_count >= max_retries, nunca resueltos)."""
    with connect() as c:
        cur = c.execute(
            "SELECT id, run_id, fuente, scope, error_type, error_message, "
            "retry_count, created_at, last_attempt_at, exhausted_at "
            "FROM failed_extractions "
            "WHERE exhausted_at IS NOT NULL AND resolved_at IS NULL "
            "ORDER BY exhausted_at DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def get_failure(failure_id: int) -> dict[str, Any] | None:
    """Devuelve un fallo por ID, incluyendo resueltos y agotados."""
    with connect() as c:
        cur = c.execute(
            "SELECT id, run_id, fuente, scope, error_type, error_message, "
            "payload_ref, retry_count, resolved_at, exhausted_at, "
            "created_at, last_attempt_at "
            "FROM failed_extractions WHERE id = ?",
            (failure_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row, strict=False))


def unresolved_summary() -> list[dict[str, Any]]:
    """Agrupa fallos abiertos por fuente/scope para priorizar acciones."""
    with connect() as c:
        cur = c.execute(
            "SELECT fuente, COALESCE(scope, '') AS scope, COUNT(*) AS n, "
            "SUM(retry_count) AS retries, MIN(created_at) AS first_seen, "
            "MAX(last_attempt_at) AS last_attempt "
            "FROM failed_extractions "
            "WHERE resolved_at IS NULL AND exhausted_at IS NULL "
            "GROUP BY fuente, COALESCE(scope, '') "
            "ORDER BY n DESC, last_attempt DESC"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def mark_resolved(failure_id: int) -> None:
    with connect() as c:
        c.execute(
            "UPDATE failed_extractions SET resolved_at = ? WHERE id = ?",
            (now_utc_iso(), failure_id),
        )


def mark_exhausted(failure_id: int) -> None:
    """Marca una entrada como agotada (no se reintentará más)."""
    with connect() as c:
        c.execute(
            "UPDATE failed_extractions SET exhausted_at = ? WHERE id = ?",
            (now_utc_iso(), failure_id),
        )


def mark_matching_resolved(fuente: str, scope: str | None = None) -> int:
    """Marca como resueltos todos los fallos abiertos de una fuente/scope."""
    with connect() as c:
        cur = c.execute(
            "UPDATE failed_extractions SET resolved_at = ? "
            "WHERE fuente = ? AND COALESCE(scope, '') = COALESCE(?, '') "
            "AND resolved_at IS NULL",
            (now_utc_iso(), fuente, scope),
        )
        return int(cur.rowcount or 0)


def increment_retry(failure_id: int) -> None:
    """Incrementa retry_count y actualiza last_attempt_at para resetear el backoff."""
    with connect() as c:
        c.execute(
            "UPDATE failed_extractions "
            "SET retry_count = retry_count + 1, last_attempt_at = ? "
            "WHERE id = ?",
            (now_utc_iso(), failure_id),
        )


def sweep_exhausted(max_retries: int) -> list[dict[str, Any]]:
    """Marca como agotadas las entradas que han alcanzado max_retries.

    Returns:
        Lista de las entradas recién marcadas como agotadas (para alertas).
    """
    with connect() as c:
        cur = c.execute(
            "SELECT id, fuente, scope, retry_count, error_message "
            "FROM failed_extractions "
            "WHERE resolved_at IS NULL AND exhausted_at IS NULL "
            "  AND retry_count >= ?",
            (max_retries,),
        )
        cols = [d[0] for d in cur.description]
        newly_exhausted = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    if not newly_exhausted:
        return []

    now = now_utc_iso()
    ids = [r["id"] for r in newly_exhausted]
    placeholders = ",".join("?" * len(ids))
    with connect() as c:
        c.execute(
            "UPDATE failed_extractions SET exhausted_at = ? WHERE id IN (" + placeholders + ")",
            [now, *ids],
        )

    log.warning(
        "dlq_entries_exhausted",
        count=len(newly_exhausted),
        fuentes=[r["fuente"] for r in newly_exhausted],
    )
    return newly_exhausted
