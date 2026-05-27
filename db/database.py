"""Capa de persistencia SQLite / Turso (libSQL) para TenderFlow."""

from __future__ import annotations

# Re-exportar desde db.connection
from db.connection import (
    close_pool,
    connect,
    connect_read,
    get_table_columns,
    is_turso_backend,
    now_utc,
    now_utc_iso,
    safe_pragma,
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
