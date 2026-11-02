"""Purga por fecha de las tablas con retención (SQL de ``scheduler/retention.py``).

La **política** —qué tabla, por qué columna, cuántos días y por qué— sigue en
``scheduler/retention.py::POLITICA_RETENCION``, que es lo que publica
``docs/SECURITY.md``. Aquí está solo la ejecución: cuenta (dry-run) o borra,
cada tabla aislada en su SAVEPOINT. Bajó aquí el 2026-10-25 (ADR-022, ratchet
TID251).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Protocol

from db.audit import purgar_extremo_antiguo
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


class _ConexionConteo(Protocol):
    """Lo que `_count_and_delete` usa de la conexión que entrega `connect()`.

    `connect()` la tipa como `Any` y la clase real
    (`db.connection._PgConnAdapter`) es privada; anotarla como `object` obligaba
    a silenciar mypy en cada `execute`. `execute` devuelve la propia conexión
    porque el adaptador une conexión y cursor, y la única fila que se lee aquí
    es la de un `COUNT(*)`.
    """

    def execute(self, sql: str, params: tuple[str], /) -> _ConexionConteo: ...

    def fetchone(self) -> tuple[int]: ...


#: Condición adicional de la purga de una tabla (constantes internas). El outbox
#: solo se purga una vez despachado: un evento pendiente es trabajo por hacer, y
#: caduque cuando caduque su fecha, no se puede perder antes de entregarse.
_SOLO_SI: dict[str, str] = {"domain_events": "dispatched_at IS NOT NULL"}


def _count_and_delete(
    conn: _ConexionConteo, table: str, date_col: str, cutoff: str, *, apply: bool
) -> int:
    extra = " AND " + _SOLO_SI[table] if table in _SOLO_SI else ""
    c = conn.execute(
        "SELECT COUNT(*) FROM " + table + " WHERE " + date_col + " < %s" + extra,
        (cutoff,),
    )
    count = c.fetchone()[0]
    if apply and count > 0:
        conn.execute(
            "DELETE FROM " + table + " WHERE " + date_col + " < %s" + extra,
            (cutoff,),
        )
    return int(count)


def purgar_por_fecha(
    rules: Sequence[tuple[str, str, int]], *, dlq_days: int, apply: bool
) -> dict[str, int]:
    """Cuenta (``apply=False``) o borra las filas anteriores al plazo de cada tabla.

    ``rules`` son ternas ``(tabla, columna_fecha, dias)`` que construye la
    política; tabla y columna son constantes internas, nunca entrada de usuario.
    Además purga ``failed_extractions`` **resueltos** con ``dlq_days`` y las
    ventanas expiradas de ``rate_limits``. Devuelve tabla → filas afectadas, o
    ``-1`` si esa tabla falló (las demás siguen).
    """
    results: dict[str, int] = {}
    with connect() as conn:
        for table, col, days in rules:
            cutoff = _cutoff_iso(days)
            with _aislado(conn, table):
                if table == "audit_log":
                    # La cadena de hashes no admite un DELETE por fecha a ciegas:
                    # `purgar_extremo_antiguo` reancla la cabecera firmada (en su
                    # propia transacción, como `rate_limits` más abajo).
                    n = purgar_extremo_antiguo(cutoff, apply=apply)
                else:
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
    return results
