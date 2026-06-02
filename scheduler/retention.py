"""Política de retención de datos — módulo del scheduler.

Extrae la lógica de ``scripts/retention_cleanup.py`` como módulo propio del
paquete ``scheduler`` para evitar el hack ``sys.path.insert`` que era necesario
para importar desde ``scripts/``.

El script CLI en ``scripts/retention_cleanup.py`` sigue funcionando y llama
esta función directamente.
"""

from __future__ import annotations

from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)


def _cutoff_iso(days: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _count_and_delete(conn: object, table: str, date_col: str, cutoff: str, *, apply: bool) -> int:

    c = conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM " + table + " WHERE " + date_col + " < ?",  # noqa: S608 — table/date_col are internal constants
        (cutoff,),
    )
    count = c.fetchone()[0]
    if apply and count > 0:
        conn.execute(  # type: ignore[attr-defined]
            "DELETE FROM " + table + " WHERE " + date_col + " < ?",  # noqa: S608 — table/date_col are internal constants
            (cutoff,),
        )
    return int(count)


def run_retention(
    *,
    runs_days: int,
    audit_days: int,
    dlq_days: int,
    history_days: int,
    access_days: int,
    idempotency_days: int = 1,
    webhook_deliveries_days: int = 90,
    apply: bool,
) -> dict[str, int]:
    """Purga registros históricos según la política de retención configurada.

    No toca las tablas ``licitaciones`` ni ``adjudicaciones``.

    Args:
        runs_days: Retención de extraction_runs (días).
        audit_days: Retención de audit_log (días).
        dlq_days: Retención de failed_extractions resueltos (días).
        history_days: Retención de licitaciones_history (días).
        access_days: Retención de access_log (días).
        idempotency_days: Retención de idempotency_keys (días).
        webhook_deliveries_days: Retención de webhook_deliveries (días).
        apply: Si False, modo dry-run (cuenta sin borrar).

    Returns:
        Dict tabla → número de registros afectados (-1 si error).
    """
    results: dict[str, int] = {}

    rules = [
        ("extraction_runs", "started_at", runs_days),
        ("audit_log", "created_at", audit_days),
        ("licitaciones_history", "changed_at", history_days),
        ("access_log", "logged_in_at", access_days),
        ("idempotency_keys", "created_at", idempotency_days),
        ("webhook_deliveries", "created_at", webhook_deliveries_days),
    ]

    with connect() as conn:
        for table, col, days in rules:
            cutoff = _cutoff_iso(days)
            try:
                n = _count_and_delete(conn, table, col, cutoff, apply=apply)
                results[table] = n
                log.info(
                    "retention.table",
                    table=table,
                    count=n,
                    days=days,
                    apply=apply,
                )
            except Exception as exc:
                log.warning("retention.table_error", table=table, error=str(exc))
                results[table] = -1

        # DLQ: solo resueltos
        cutoff_dlq = _cutoff_iso(dlq_days)
        try:
            cur = conn.execute(
                "SELECT COUNT(*) FROM failed_extractions "
                "WHERE resolved_at IS NOT NULL AND resolved_at < ?",
                (cutoff_dlq,),
            )
            n_dlq = cur.fetchone()[0]
            if apply and n_dlq > 0:
                conn.execute(
                    "DELETE FROM failed_extractions "
                    "WHERE resolved_at IS NOT NULL AND resolved_at < ?",
                    (cutoff_dlq,),
                )
            results["failed_extractions"] = int(n_dlq)
            log.info(
                "retention.table",
                table="failed_extractions",
                count=n_dlq,
                days=dlq_days,
                apply=apply,
            )
        except Exception as exc:
            log.warning("retention.table_error", table="failed_extractions", error=str(exc))
            results["failed_extractions"] = -1

        # rate_limits: purgar entradas expiradas
        try:
            from db.rate_limits import cleanup_expired

            if apply:
                n_rl = cleanup_expired()
            else:
                import time as _time

                now_ts = _time.time()
                cur_rl = conn.execute(
                    "SELECT COUNT(*) FROM rate_limits WHERE reset_at < ?", (now_ts,)
                )
                n_rl = cur_rl.fetchone()[0]
            results["rate_limits"] = int(n_rl)
            log.info("retention.table", table="rate_limits", count=n_rl, days=0, apply=apply)
        except Exception as exc:
            log.warning("retention.table_error", table="rate_limits", error=str(exc))
            results["rate_limits"] = -1

    total = sum(v for v in results.values() if v >= 0)
    log.info("retention.done", total=total, apply=apply, tables=list(results.keys()))
    return results
