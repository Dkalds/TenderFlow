"""Política de retención de datos — módulo del scheduler.

Extrae la lógica de ``scripts/retention_cleanup.py`` como módulo propio del
paquete ``scheduler`` para evitar el hack ``sys.path.insert`` que era necesario
para importar desde ``scripts/``.

El script CLI en ``scripts/retention_cleanup.py`` sigue funcionando y llama
esta función directamente.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)


@contextmanager
def _aislado(conn: Any, etiqueta: str) -> Iterator[None]:
    """Aísla un bloque de la purga para que su fallo no tumbe el resto.

    El ``try/except`` por tabla daba **falsa seguridad** en Postgres: cuando una
    sentencia falla (tabla ausente, permisos, tipo incompatible), Postgres
    aborta la transacción entera y todas las sentencias posteriores devuelven
    ``current transaction is aborted``. En la práctica, un fallo en la primera
    tabla dejaba sin purgar todas las demás y el job lo reportaba como -1 sin
    más ruido. SQLite, en cambio, continúa tras el error, así que la suite
    —que corría sobre SQLite— nunca lo vio (ADR-018).

    Un SAVEPOINT por bloque restaura el comportamiento esperado en ambos
    motores. Mismo patrón que ``db/upsert.py::replace_adjudicaciones``.
    """
    sp = f"retention_{etiqueta}"

    def _sp(sentencia: str) -> None:
        """Ejecuta bookkeeping del savepoint sin dejar que tumbe la purga.

        El savepoint puede haber desaparecido legítimamente: algunos bloques
        (``rate_limits`` → ``db.rate_limits.cleanup_expired``) abren su propia
        conexión y hacen commit, lo que en SQLite cierra la transacción y
        destruye los savepoints abiertos. Fallar aquí convertiría un detalle de
        control de flujo en un error de purga.
        """
        try:
            conn.execute(sentencia)
        except Exception:
            log.debug("retention.savepoint_noop", stmt=sentencia)

    _sp(f"SAVEPOINT {sp}")
    try:
        yield
    except Exception as exc:
        _sp(f"ROLLBACK TO SAVEPOINT {sp}")
        log.warning("retention.table_error", table=etiqueta, error=str(exc))
    finally:
        _sp(f"RELEASE SAVEPOINT {sp}")


def _cutoff_iso(days: int) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _count_and_delete(conn: object, table: str, date_col: str, cutoff: str, *, apply: bool) -> int:

    c = conn.execute(  # type: ignore[attr-defined]
        "SELECT COUNT(*) FROM " + table + " WHERE " + date_col + " < %s",  # noqa: S608 — table/date_col are internal constants
        (cutoff,),
    )
    count = c.fetchone()[0]
    if apply and count > 0:
        conn.execute(  # type: ignore[attr-defined]
            "DELETE FROM " + table + " WHERE " + date_col + " < %s",  # noqa: S608 — table/date_col are internal constants
            (cutoff,),
        )
    return int(count)


#: Meses que se conservan las solicitudes de acceso.
#:
#: **Es un plazo publicado, no una preferencia operativa**: el aviso legal lo
#: anuncia al visitante en el momento de la recogida
#: (`web/src/lib/legal.ts::LEGAL_MESES_RETENCION_SOLICITUDES`), que es lo que
#: exige el RGPD. Antes no había ninguno y el aviso lo decía —«hoy no existe un
#: borrado automático por plazo»—, que es honesto y no es cumplir.
#:
#: Los dos números tienen que coincidir; lo comprueba
#: `tests/test_retention_solicitudes.py`, porque una divergencia aquí convierte
#: el aviso en una promesa falsa sin que falle nada.
SOLICITUDES_ACCESO_RETENTION_MESES = 24
SOLICITUDES_ACCESO_RETENTION_DAYS = SOLICITUDES_ACCESO_RETENTION_MESES * 30
PASSWORD_RESET_RETENTION_DAYS = 7

# Columna de fecha por la que se purga cada tabla. Vive fuera de
# ``run_retention`` para que un test la pueda cotejar contra el schema real,
# que es lo que faltaba: hasta 2026-09 ``licitaciones_history`` apuntaba a
# ``changed_at`` y la columna se llama ``captured_at``. El bucle aísla cada
# tabla en su savepoint y anota ``-1`` si falla, así que el
# ``UndefinedColumn`` se tragaba pasada tras pasada: esa retención no purgó
# nunca y el error salía a diario sin que nadie lo leyera como un error.
#
# Hoy no hay daño acumulado —la ventana es de 365 días y la tabla arranca en
# mayo de 2026, así que no había nada que borrar— pero un error recurrente en
# el log es exactamente lo que hace invisible al siguiente.
COLUMNA_FECHA: dict[str, str] = {
    "extraction_runs": "started_at",
    "audit_log": "created_at",
    "licitaciones_history": "captured_at",
    "access_log": "logged_in_at",
    "idempotency_keys": "created_at",
    "webhook_deliveries": "created_at",
    "solicitudes_acceso": "created_at",
    # pragma: allowlist secret -- nombre de tabla y de columna, no una credencial
    "password_reset_tokens": "created_at",  # pragma: allowlist secret
}


def run_retention(
    *,
    runs_days: int,
    audit_days: int,
    dlq_days: int,
    history_days: int,
    access_days: int,
    idempotency_days: int = 1,
    webhook_deliveries_days: int = 90,
    solicitudes_acceso_days: int = SOLICITUDES_ACCESO_RETENTION_DAYS,
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
        solicitudes_acceso_days: Retención de solicitudes_acceso (días). Es el
            plazo que el aviso legal publica; ver la constante de este módulo.
        apply: Si False, modo dry-run (cuenta sin borrar).

    Returns:
        Dict tabla → número de registros afectados (-1 si error).
    """
    results: dict[str, int] = {}

    rules = [
        (tabla, COLUMNA_FECHA[tabla], dias)
        for tabla, dias in (
            ("extraction_runs", runs_days),
            ("audit_log", audit_days),
            ("licitaciones_history", history_days),
            ("access_log", access_days),
            ("idempotency_keys", idempotency_days),
            ("webhook_deliveries", webhook_deliveries_days),
            # Datos de contacto de personas que escribieron desde la página
            # pública. Se borran por plazo con independencia de su estado: una
            # solicitud de hace dos años está abandonada, atendida o
            # descartada, y en los tres casos ya no hay finalidad que
            # justifique conservarla.
            ("solicitudes_acceso", solicitudes_acceso_days),
            # Tokens usados o caducados no aportan valor operativo. La tabla
            # sólo contiene hashes, pero la minimización también aplica a
            # identificadores indirectos y a credenciales ya inválidas.
            ("password_reset_tokens", PASSWORD_RESET_RETENTION_DAYS),
        )
    ]

    with connect() as conn:
        for table, col, days in rules:
            cutoff = _cutoff_iso(days)
            with _aislado(conn, table):
                n = _count_and_delete(conn, table, col, cutoff, apply=apply)
                results[table] = n
                log.info(
                    "retention.table",
                    table=table,
                    count=n,
                    days=days,
                    apply=apply,
                )
            results.setdefault(table, -1)

        # DLQ: solo resueltos
        cutoff_dlq = _cutoff_iso(dlq_days)
        with _aislado(conn, "failed_extractions"):
            cur = conn.execute(
                "SELECT COUNT(*) FROM failed_extractions "
                "WHERE resolved_at IS NOT NULL AND resolved_at < %s",
                (cutoff_dlq,),
            )
            n_dlq = cur.fetchone()[0]
            if apply and n_dlq > 0:
                conn.execute(
                    "DELETE FROM failed_extractions "
                    "WHERE resolved_at IS NOT NULL AND resolved_at < %s",
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
        results.setdefault("failed_extractions", -1)

        # rate_limits: purgar entradas expiradas
        with _aislado(conn, "rate_limits"):
            from db.rate_limits import cleanup_expired

            if apply:
                n_rl = cleanup_expired()
            else:
                import time as _time

                now_ts = _time.time()
                cur_rl = conn.execute(
                    "SELECT COUNT(*) FROM rate_limits WHERE reset_at < %s", (now_ts,)
                )
                n_rl = cur_rl.fetchone()[0]
            results["rate_limits"] = int(n_rl)
            log.info("retention.table", table="rate_limits", count=n_rl, days=0, apply=apply)
        results.setdefault("rate_limits", -1)

    total = sum(v for v in results.values() if v >= 0)
    log.info("retention.done", total=total, apply=apply, tables=list(results.keys()))
    return results
