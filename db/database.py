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

# Re-exportar desde db.connection
from config import settings
from db.connection import (
    _DB_PATH_OVERRIDE,
    _db_initialized,
    _local,
    _pool,
    _pool_lock,
    _get_conn,
    _return_conn,
    close_pool,
    connect,
    connect_read as _connect_read_impl,
    get_table_columns,
    is_turso_backend,
    now_utc,
    now_utc_iso,
    safe_pragma as _safe_pragma_impl,
    set_db_path_override,
)


from typing import Any as _Any


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
    import db.connection as _conn_mod
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


# Re-exportar desde db.schema
from db.schema import (
    SCHEMA,
    _ensure_licitaciones_columns,
    init_db,
)

# Re-exportar desde db.upsert
from db.upsert import (
    Adjudicacion,
    Licitacion,
    UpsertResult,
    _ADJ_COLS,
    _ADJ_KEYS,
    _ADJ_PLACEHOLDERS,
    _HISTORY_SELECT_COLS,
    _LIC_COLS,
    _LIC_KEYS,
    _LIC_PLACEHOLDERS,
    _LIC_UPDATES,
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
