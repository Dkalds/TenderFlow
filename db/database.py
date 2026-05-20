"""Capa de persistencia SQLite / Turso (libSQL) para licitaciones.

Este módulo es una **fachada** que re-exporta los símbolos públicos de los
sub-módulos especializados:

- ``db.connection``  — pool, ``connect()``, ``connect_read()``, helpers
- ``db.schema``      — DDL ``SCHEMA``, ``init_db()``
- ``db.upsert``      — dataclasses, operaciones de escritura, historial, FTS

Mantener este módulo como punto de entrada único preserva la compatibilidad
con todos los importadores existentes sin necesidad de cambios en ellos.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any as _Any

# Re-exportar desde db.connection
from config import settings
from db.connection import (
    _get_conn,
    _return_conn,
    close_pool,
    connect,
    get_table_columns,
    is_turso_backend,
    now_utc,
    now_utc_iso,
    set_db_path_override,
)

# Re-exportar desde db.schema
from db.schema import (
    SCHEMA,
    init_db,
)

# Re-exportar desde db.upsert
from db.upsert import (
    Adjudicacion,
    Licitacion,
    UpsertResult,
    count_licitaciones,
    fts_available,
    get_cursor,
    get_history,
    log_extraccion,
    replace_adjudicaciones,
    search_fts,
    set_cursor,
    upsert_licitaciones,
    upsert_licitaciones_with_history,
)


def safe_pragma(conn: _Any, stmt: str) -> None:
    """Wrapper de safe_pragma que usa is_turso_backend del módulo actual."""
    if is_turso_backend():
        return
    try:
        conn.execute(stmt)
    except Exception:
        pass


@contextmanager
def connect_read() -> Iterator[_Any]:
    """Wrapper de connect_read que usa safe_pragma del módulo actual."""
    replica_url = settings.TURSO_REPLICA_URL
    if replica_url:
        try:
            import libsql_experimental as libsql_exp

            conn = libsql_exp.connect(
                replica_url,
                auth_token=settings.TURSO_AUTH_TOKEN,
            )
            try:
                yield conn
            finally:
                conn.close()
            return
        except ImportError:
            pass
    conn = _get_conn()
    try:
        safe_pragma(conn, "PRAGMA query_only = ON")
        yield conn
    finally:
        safe_pragma(conn, "PRAGMA query_only = OFF")
        _return_conn(conn)


__all__ = [
    # connection
    "connect",
    "connect_read",
    "close_pool",
    "get_table_columns",
    "is_turso_backend",
    "now_utc",
    "now_utc_iso",
    "safe_pragma",
    "set_db_path_override",
    # schema
    "SCHEMA",
    "init_db",
    # upsert
    "Adjudicacion",
    "Licitacion",
    "UpsertResult",
    "count_licitaciones",
    "fts_available",
    "get_cursor",
    "get_history",
    "log_extraccion",
    "replace_adjudicaciones",
    "search_fts",
    "set_cursor",
    "upsert_licitaciones",
    "upsert_licitaciones_with_history",
]
