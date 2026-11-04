"""Purga por fecha de las tablas con retención (SQL de ``scheduler/retention.py``).

La **política** —qué tabla, por qué columna, cuántos días y por qué— sigue en
``scheduler/retention.py::POLITICA_RETENCION``, que es lo que publica
``docs/SECURITY.md``. Aquí está solo la ejecución: cuenta (dry-run) o borra.
Bajó aquí el 2026-10-25 (ADR-022, ratchet TID251).

Cada tabla se purga por su cuenta y por lotes, con un commit por lote. Hasta
2026-11 todas compartían UNA transacción con un ``COUNT(*)`` y un ``DELETE``
masivo por tabla: la primera purga de una tabla grande retenía sus locks y el
WAL de todas las demás hasta el final, y un fallo a mitad deshacía lo ya
borrado. Una tabla que falla anota ``-1`` y las demás siguen; quien llama
decide que eso es un fallo del paso (``scheduler.retention.exigir_completa``).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from functools import partial

from db.audit import purgar_extremo_antiguo
from db.database import connect
from observability.logging import get_logger

log = get_logger(__name__)

#: Filas por sentencia de borrado. Acota cuánto dura cada transacción —y por
#: tanto cuánto bloquea y cuánto WAL acumula— sin multiplicar los viajes a la
#: base en las purgas normales, que son de cientos de filas.
LOTE_BORRADO = 5000


def _cutoff_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


#: Condición adicional de la purga de una tabla (constantes internas). El outbox
#: solo se purga una vez despachado: un evento pendiente es trabajo por hacer, y
#: caduque cuando caduque su fecha, no se puede perder antes de entregarse.
_SOLO_SI: dict[str, str] = {"domain_events": "dispatched_at IS NOT NULL"}


def _purgar_tabla(table: str, date_col: str, cutoff: str, *, apply: bool) -> int:
    """Cuenta (dry-run) o borra por lotes las filas de ``table`` anteriores a ``cutoff``.

    El lote se elige por ``ctid`` porque no todas las tablas tienen una
    columna ``id`` y ``DELETE`` no admite ``LIMIT``; ``ctid = ANY(ARRAY(…))``
    lo resuelve Postgres con un TID scan. Una fila que otro proceso actualiza
    entre medias cambia de ``ctid`` y se salta: la recoge el lote siguiente o
    la pasada de mañana.
    """
    where = date_col + " < %s" + (" AND " + _SOLO_SI[table] if table in _SOLO_SI else "")
    if not apply:
        with connect() as conn:
            fila = conn.execute("SELECT COUNT(*) FROM " + table + " WHERE " + where, (cutoff,))
            return int(fila.fetchone()[0])

    total = 0
    while True:
        with connect() as conn:
            borradas = int(
                conn.execute(
                    "DELETE FROM " + table + " WHERE ctid = ANY(ARRAY("
                    "SELECT ctid FROM " + table + " WHERE " + where + " LIMIT %s))",
                    (cutoff, LOTE_BORRADO),
                ).rowcount
            )
        total += borradas
        if borradas < LOTE_BORRADO:
            return total


def _contar_rate_limits_expirados() -> int:
    import time

    with connect() as conn:
        fila = conn.execute("SELECT COUNT(*) FROM rate_limits WHERE reset_at < %s", (time.time(),))
        return int(fila.fetchone()[0])


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
    from db.rate_limits import cleanup_expired

    trabajos: list[tuple[str, int, Callable[[], int]]] = []
    for table, col, days in rules:
        cutoff = _cutoff_iso(days)
        if table == "audit_log":
            # La cadena de hashes no admite un DELETE por fecha a ciegas:
            # `purgar_extremo_antiguo` reancla la cabecera firmada.
            trabajos.append((table, days, partial(purgar_extremo_antiguo, cutoff, apply=apply)))
        else:
            trabajos.append((table, days, partial(_purgar_tabla, table, col, cutoff, apply=apply)))
    # DLQ: solo resueltos (`resolved_at < corte` ya excluye los abiertos, NULL).
    trabajos.append(
        (
            "failed_extractions",
            dlq_days,
            partial(
                _purgar_tabla,
                "failed_extractions",
                "resolved_at",
                _cutoff_iso(dlq_days),
                apply=apply,
            ),
        )
    )
    # rate_limits: ventanas expiradas, sin plazo.
    trabajos.append(("rate_limits", 0, cleanup_expired if apply else _contar_rate_limits_expirados))

    results: dict[str, int] = {}
    for table, days, purgar in trabajos:
        try:
            n = purgar()
        except Exception as exc:
            log.warning("retention.table_error", table=table, error=str(exc), exc_info=True)
            results[table] = -1
            continue
        results[table] = n
        log.info("retention.table", table=table, count=n, days=days, apply=apply)
    return results
