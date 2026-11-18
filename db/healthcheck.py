"""SQL del healthcheck del pipeline (``scheduler/healthcheck.py``).

El healthcheck mide en UNA transacción, que abre :func:`en_transaccion`, y
cada bloque recibe esa conexión y la reenvía a estas funciones (ADR-022: todo
el SQL vive en ``db/``). Los ROLLBACK tras una consulta fallida se quedan en
el healthcheck, que es quien decide qué bloque degrada a aviso y cuál sigue:
aquí solo está la consulta.

Módulo de funciones, no clase: mismo estrato que ``db/repositories/*``
(AGENTS.md §3.10).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from db.database import connect, estimar_filas

if TYPE_CHECKING:
    from collections.abc import Callable

    from db.connection import _PgConnAdapter

T = TypeVar("T")


def en_transaccion(fn: Callable[[_PgConnAdapter], T]) -> T:
    """Corre ``fn(conn)`` en una única transacción de escritura y devuelve su resultado.

    Commit al salir (la retención de ``ops_events`` borra); si ``fn`` lanza,
    rollback y la excepción sigue su curso.
    """
    with connect() as conn:
        return fn(conn)


def contar_licitaciones(c: _PgConnAdapter) -> tuple[int, bool]:
    """Filas de ``licitaciones``: estimación del planner, exacta si no sirve.

    Devuelve ``(total, estimado)``.

    El ``COUNT(*)`` exacto es un seq scan de la tabla más grande de la BD y era
    la PRIMERA consulta del healthcheck: cuando cruzó el ``statement_timeout``
    de 30 s (2026-08), el ``QueryCanceled`` reventó el healthcheck entero antes
    de ejecutar ningún otro check y el post-run del scraper murió con traceback
    en vez de reportar estado. El razonamiento completo, en ``estimar_filas``.
    """
    aproximado = estimar_filas(c, "licitaciones")
    if aproximado is not None:
        return aproximado, True
    return int(c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()[0]), False


def tamano_bd(c: _PgConnAdapter) -> int:
    """Bytes de la base actual (``pg_database_size``)."""
    return int(c.execute("SELECT pg_database_size(current_database())").fetchone()[0])


def ultimo_extraction_run(c: _PgConnAdapter) -> tuple[object, ...] | None:
    """``(run_id, started_at, status, months_ok, months_failed)`` del último run, o ``None``."""
    fila: tuple[object, ...] | None = c.execute(
        "SELECT run_id, started_at, status, months_ok, months_failed "
        "FROM extraction_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return fila


def dlq_sin_resolver(c: _PgConnAdapter) -> int:
    """Entradas de ``failed_extractions`` sin resolver."""
    return int(
        c.execute("SELECT COUNT(*) FROM failed_extractions WHERE resolved_at IS NULL").fetchone()[0]
    )


def adjudicaciones_enlazadas(c: _PgConnAdapter) -> tuple[int, int]:
    """``(total, con_empresa)`` de ``adjudicaciones``: un recorrido completo de la tabla."""
    total, enlazadas = c.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN empresa_id IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM adjudicaciones"
    ).fetchone()
    return int(total or 0), int(enlazadas or 0)


def ultimo_kpi_snapshot(c: _PgConnAdapter) -> object:
    """``computed_at`` del último ``kpi_snapshots``, o ``None`` si no hay ninguno."""
    fila = c.execute(
        "SELECT computed_at FROM kpi_snapshots ORDER BY computed_at DESC LIMIT 1"
    ).fetchone()
    return fila[0] if fila else None


def locks_vigentes(c: _PgConnAdapter, ahora_iso: str) -> list[dict[str, object]]:
    """Locks de ``job_locks`` que caducan después de ``ahora_iso`` (ADR-012)."""
    filas = c.execute(
        "SELECT name, holder, expires_at FROM job_locks WHERE expires_at > %s",
        (ahora_iso,),
    ).fetchall()
    return [{"name": r[0], "holder": r[1], "expires_at": r[2]} for r in filas]


def ops_events_por_tipo(
    c: _PgConnAdapter, desde_6h: str, desde_24h: str
) -> list[tuple[str, int, int]]:
    """``(event_type, n_desde_6h, n_desde_24h)`` de ``ops_events`` en las últimas 24 h."""
    filas = c.execute(
        "SELECT event_type, COUNT(*) FILTER (WHERE ts > %s), COUNT(*) "
        "FROM ops_events WHERE ts > %s GROUP BY event_type",
        (desde_6h, desde_24h),
    ).fetchall()
    return [(str(r[0]), int(r[1]), int(r[2])) for r in filas]


def purgar_ops_events(c: _PgConnAdapter, antes_de: str) -> None:
    """Borra los ``ops_events`` anteriores a ``antes_de`` (retención de 30 días)."""
    c.execute("DELETE FROM ops_events WHERE ts < %s", (antes_de,))
