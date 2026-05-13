"""Reintento automático de extracciones fallidas en la Dead Letter Queue.

Para cada entrada no resuelta, aplica backoff exponencial antes de reintentar:
    espera = min(2^retry_count * 300s, 86400s)

Si el reintento tiene éxito se marca como resuelta; si falla, incrementa
``retry_count`` y registra el nuevo error, para que el próximo ciclo
respete el backoff correctamente.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from db.dlq import increment_retry, list_unresolved, mark_resolved
from observability.logging import bind_run_context, get_logger

log = get_logger(__name__)

# Tiempo base de espera entre reintentos (segundos): 2^retry_count * _BASE_BACKOFF_S
_BASE_BACKOFF_S = 300  # 5 minutos
_MAX_BACKOFF_S = 86_400  # 24 horas
_DEFAULT_MAX_RETRIES = 5
_DEFAULT_BATCH_SIZE = 10


def _backoff_seconds(retry_count: int) -> float:
    """Calcula el tiempo de espera para un fallo con *retry_count* reintentos previos."""
    return float(min(_BASE_BACKOFF_S * (2**retry_count), _MAX_BACKOFF_S))


def _is_due(failure: dict[str, Any]) -> bool:
    """Devuelve True si ya ha pasado suficiente tiempo desde el último intento."""
    created_raw = failure.get("created_at")
    if not created_raw:
        return True
    try:
        last_attempt = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return True
    retry_count = int(failure.get("retry_count") or 0)
    due_after = last_attempt + timedelta(seconds=_backoff_seconds(retry_count))
    return datetime.now(UTC) >= due_after


def _retry_failure(failure: dict[str, Any], run_id: str) -> bool:
    """Intenta re-ejecutar la extracción correspondiente a *failure*.

    Returns:
        True si el reintento fue exitoso; False si falló de nuevo.
    """
    fuente: str = str(failure.get("fuente") or "")
    scope: str = str(failure.get("scope") or "")

    try:
        if fuente.startswith("bulk_"):
            # Formato: bulk_YYYYMM
            ym = fuente[len("bulk_") :]
            if len(ym) == 6 and ym.isdigit():
                year, month = int(ym[:4]), int(ym[4:])
                from scraper.pipeline import process_month

                result = process_month(year, month, run_id=run_id)
                if result.get("status") == "ok":
                    return True
                log.warning(
                    "dlq_retry_bulk_failed",
                    failure_id=failure["id"],
                    year=year,
                    month=month,
                    status=result.get("status"),
                )
                return False
            log.warning("dlq_retry_unknown_bulk_format", fuente=fuente)
            return False

        elif fuente == "place_live_atom" or fuente.startswith("atom"):
            # Re-lanzar el scraping del feed diario (idempotente por upserts)
            from scraper.pipeline import process_daily

            result = process_daily(run_id=run_id)
            if result.get("status") == "ok":
                return True
            log.warning(
                "dlq_retry_atom_failed",
                failure_id=failure["id"],
                status=result.get("status"),
            )
            return False

        else:
            log.warning(
                "dlq_retry_unknown_source",
                failure_id=failure["id"],
                fuente=fuente,
                scope=scope,
            )
            return False

    except Exception as exc:
        log.exception(
            "dlq_retry_exception",
            failure_id=failure["id"],
            fuente=fuente,
            error=str(exc),
        )
        return False


def retry_failed_extractions(
    max_retries: int = _DEFAULT_MAX_RETRIES,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> int:
    """Reintenta extracciones fallidas pendientes en la DLQ.

    Solo procesa entradas con ``retry_count < max_retries`` y cuyo backoff
    exponencial ya ha expirado. Devuelve el número de fallos resueltos.

    Args:
        max_retries: Máximo de reintentos antes de abandonar una entrada.
        batch_size: Número máximo de entradas a procesar por ejecución.

    Returns:
        Número de fallos que se han resuelto exitosamente.
    """
    unresolved = [
        f
        for f in list_unresolved(limit=batch_size * 3)
        if int(f.get("retry_count") or 0) < max_retries
    ]

    if not unresolved:
        log.debug("dlq_retry_nothing_pending")
        return 0

    # Filtrar solo los que ya han cumplido el backoff
    due = [f for f in unresolved if _is_due(f)][:batch_size]

    if not due:
        log.debug("dlq_retry_all_in_backoff", total_unresolved=len(unresolved))
        return 0

    log.info("dlq_retry_starting", due=len(due), total_unresolved=len(unresolved))
    run_id = bind_run_context(entrypoint="dlq_retry", batch=len(due))

    resolved = 0
    for failure in due:
        fid = int(failure["id"])
        success = _retry_failure(failure, run_id)
        if success:
            mark_resolved(fid)
            resolved += 1
            log.info("dlq_retry_resolved", failure_id=fid, fuente=failure.get("fuente"))
        else:
            increment_retry(fid)
            log.warning(
                "dlq_retry_still_failing",
                failure_id=fid,
                fuente=failure.get("fuente"),
                new_retry_count=int(failure.get("retry_count") or 0) + 1,
            )

    log.info("dlq_retry_done", resolved=resolved, attempted=len(due))
    return resolved
