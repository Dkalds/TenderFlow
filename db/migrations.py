"""Sistema simple de migraciones basado en tabla ``schema_version``.

Cada migración es una tupla ``(version, description, sql)``. Se aplican en
orden ascendente y la versión actual queda registrada en ``schema_version``.

Diseñado para proyectos pequeños donde un Alembic completo es overkill pero
mantener un historial auditable sigue siendo importante.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


# Lista append-only: nunca modificar una migración ya desplegada — añadir otra.
MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "baseline_and_run_metrics",
        """
        CREATE TABLE IF NOT EXISTS extraction_runs (
            run_id                  TEXT PRIMARY KEY,
            started_at              TEXT NOT NULL,
            ended_at                TEXT,
            duration_ms             INTEGER,
            status                  TEXT NOT NULL,
            months_attempted        INTEGER DEFAULT 0,
            months_ok               INTEGER DEFAULT 0,
            months_failed           INTEGER DEFAULT 0,
            licitaciones_nuevas     INTEGER DEFAULT 0,
            licitaciones_actualizadas INTEGER DEFAULT 0,
            adjudicaciones          INTEGER DEFAULT 0,
            errores_parseo          INTEGER DEFAULT 0,
            errores_descarga        INTEGER DEFAULT 0,
            notas                   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_runs_started ON extraction_runs(started_at);
        CREATE INDEX IF NOT EXISTS idx_runs_status  ON extraction_runs(status);

        CREATE TABLE IF NOT EXISTS failed_extractions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT,
            fuente          TEXT NOT NULL,
            scope           TEXT,
            error_type      TEXT,
            error_message   TEXT,
            payload_ref     TEXT,
            retry_count     INTEGER DEFAULT 0,
            resolved_at     TEXT,
            created_at      TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_fail_run ON failed_extractions(run_id);
        CREATE INDEX IF NOT EXISTS idx_fail_unresolved ON failed_extractions(resolved_at);
        """,
    ),
    (
        2,
        "user_watchlist",
        """
        CREATE TABLE IF NOT EXISTS watchlist_cpv (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key        TEXT NOT NULL,
            cpv_prefix      TEXT NOT NULL,
            keyword         TEXT,
            min_importe     REAL,
            ccaa            TEXT,
            created_at      TEXT NOT NULL,
            UNIQUE(user_key, cpv_prefix, keyword, ccaa)
        );
        CREATE INDEX IF NOT EXISTS idx_wl_user ON watchlist_cpv(user_key);
        """,
    ),
    (
        3,
        "watchlist_last_notified",
        """
        ALTER TABLE watchlist_cpv ADD COLUMN last_notified_at TEXT;
        """,
    ),
    (
        4,
        "watchlist_email",
        """
        ALTER TABLE watchlist_cpv ADD COLUMN email TEXT;
        """,
    ),
    (
        5,
        "ingestion_cursors_and_history",
        """
        CREATE TABLE IF NOT EXISTS ingestion_cursors (
            source              TEXT PRIMARY KEY,
            last_seen_updated   TEXT,
            last_entry_id       TEXT,
            etag                TEXT,
            last_modified       TEXT,
            updated_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS licitaciones_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            id_externo      TEXT NOT NULL,
            captured_at     TEXT NOT NULL,
            source          TEXT,
            snapshot_json   TEXT NOT NULL,
            changed_fields  TEXT NOT NULL,
            FOREIGN KEY(id_externo) REFERENCES licitaciones(id_externo)
        );
        CREATE INDEX IF NOT EXISTS idx_hist_externo ON licitaciones_history(id_externo, captured_at);
        """,
    ),
    (
        6,
        "licitaciones_extra_columns",
        """
        -- Columnas previamente añadidas por _migrate() en database.py.
        -- ALTER TABLE ADD COLUMN es idempotente en SQLite (falla silenciosamente
        -- si la columna ya existe según el IF NOT EXISTS workaround).
        -- Usamos subconsultas PRAGMA para comprobar existencia.
        """,
    ),
    (
        7,
        "fts5_licitaciones",
        """
        -- Se aplica de forma programática en _apply_v7_fts() porque
        -- requiere que la tabla licitaciones exista y necesita rebuild
        -- del índice con datos existentes.
        """,
    ),
    (
        8,
        "users_and_watchlist_user_id",
        """
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            email           TEXT UNIQUE,
            oauth_provider  TEXT,
            oauth_sub       TEXT,
            display_name    TEXT,
            created_at      TEXT NOT NULL,
            UNIQUE(oauth_provider, oauth_sub)
        );
        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_users_oauth ON users(oauth_provider, oauth_sub);
        """,
    ),
    (
        9,
        "access_log",
        """
        CREATE TABLE IF NOT EXISTS access_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER,
            email           TEXT,
            auth_method     TEXT NOT NULL,
            logged_in_at    TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_access_log_user ON access_log(user_id);
        CREATE INDEX IF NOT EXISTS idx_access_log_time ON access_log(logged_in_at);
        """,
    ),
    (
        10,
        "users_is_admin",
        "",  # handled programmatically
    ),
    (
        11,
        "failed_extractions_dedup_index",
        """
        -- Índice único parcial para deduplicar fallos no resueltos.
        -- Permite usar UPSERT en record_failure() para incrementar retry_count
        -- cuando el mismo (fuente, scope, payload_ref) vuelve a fallar.
        -- COALESCE necesario porque SQLite trata cada NULL como distinto.
        CREATE UNIQUE INDEX IF NOT EXISTS idx_fail_unique_unresolved
        ON failed_extractions(fuente, COALESCE(scope, ''), COALESCE(payload_ref, ''))
        WHERE resolved_at IS NULL;
        """,
    ),
]

# Columnas de la migración 6 — se aplican de forma programática porque
# SQLite no soporta IF NOT EXISTS en ALTER TABLE ADD COLUMN.
_V6_COLUMNS: list[tuple[str, str]] = [
    ("duracion_valor", "REAL"),
    ("duracion_unidad", "TEXT"),
    ("fecha_inicio", "TEXT"),
    ("fecha_fin", "TEXT"),
    ("prorroga_descripcion", "TEXT"),
    ("fecha_actualizacion_fuente", "TEXT"),
]


import re

_VALID_COLUMN_NAME = re.compile(r"^[a-zA-Z_]\w*$")


def _ensure_version_table(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  TEXT NOT NULL
        )
        """
    )


def current_version(conn: Any) -> int:
    _ensure_version_table(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return int(row[0] or 0)


def apply_pending(conn: Any) -> list[int]:
    """Aplica todas las migraciones pendientes. Devuelve las versiones aplicadas."""
    applied: list[int] = []
    _ensure_version_table(conn)
    current = current_version(conn)
    for version, description, sql in sorted(MIGRATIONS, key=lambda m: m[0]):
        if version <= current:
            continue
        log.info("migration_applying", version=version, description=description)
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt and not stmt.startswith("--"):
                conn.execute(stmt)
        # Migración 6: ALTER TABLE ADD COLUMN programático
        if version == 6:
            _apply_v6_columns(conn)
        # Migración 7: FTS5 + triggers + rebuild
        if version == 7:
            _apply_v7_fts(conn)
        # Migración 8: user_id column on watchlist_cpv
        if version == 8:
            _apply_v8_user_id(conn)
        # Migración 10: is_admin column on users
        if version == 10:
            _apply_v10_is_admin(conn)
        conn.execute(
            "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
            (version, description, datetime.now(timezone.utc).isoformat()),
        )
        applied.append(version)
    if applied:
        log.info("migrations_applied", versions=applied)
    return applied


def _apply_v6_columns(conn: Any) -> None:
    """Añade columnas extra a licitaciones si no existen (idempotente)."""
    # Si la tabla no existe aún (e.g. test de migraciones puro), no hay nada que hacer.
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='licitaciones'"
    ).fetchone()
    if not exists:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(licitaciones)").fetchall()}
    for name, ctype in _V6_COLUMNS:
        if not _VALID_COLUMN_NAME.match(name):
            raise ValueError(f"Nombre de columna no válido: {name!r}")
        if name not in cols:
            conn.execute(f"ALTER TABLE licitaciones ADD COLUMN {name} {ctype}")


_V7_FTS_STATEMENTS: list[str] = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS licitaciones_fts USING fts5(
        id_externo UNINDEXED,
        titulo,
        descripcion,
        content=licitaciones,
        content_rowid=rowid
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_fts_insert AFTER INSERT ON licitaciones BEGIN
        INSERT INTO licitaciones_fts(rowid, id_externo, titulo, descripcion)
        VALUES (new.rowid, new.id_externo, new.titulo, new.descripcion);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_fts_delete BEFORE DELETE ON licitaciones BEGIN
        INSERT INTO licitaciones_fts(licitaciones_fts, rowid, id_externo, titulo, descripcion)
        VALUES ('delete', old.rowid, old.id_externo, old.titulo, old.descripcion);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_fts_update BEFORE UPDATE ON licitaciones BEGIN
        INSERT INTO licitaciones_fts(licitaciones_fts, rowid, id_externo, titulo, descripcion)
        VALUES ('delete', old.rowid, old.id_externo, old.titulo, old.descripcion);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_fts_update_after AFTER UPDATE ON licitaciones BEGIN
        INSERT INTO licitaciones_fts(rowid, id_externo, titulo, descripcion)
        VALUES (new.rowid, new.id_externo, new.titulo, new.descripcion);
    END
    """,
]


def _apply_v7_fts(conn: Any) -> None:
    """Crea tabla FTS5, triggers y rebuild del índice (idempotente)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='licitaciones'"
    ).fetchone()
    if not exists:
        return
    for stmt in _V7_FTS_STATEMENTS:
        conn.execute(stmt)
    # Rebuild: populate FTS index with existing data
    conn.execute("INSERT INTO licitaciones_fts(licitaciones_fts) VALUES('rebuild')")


def _apply_v8_user_id(conn: Any) -> None:
    """Añade user_id a watchlist_cpv si no existe (idempotente)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='watchlist_cpv'"
    ).fetchone()
    if not exists:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(watchlist_cpv)").fetchall()}
    if "user_id" not in cols:
        conn.execute(
            "ALTER TABLE watchlist_cpv ADD COLUMN user_id INTEGER REFERENCES users(id)"
        )
    # Index for user_id lookups (idempotent via IF NOT EXISTS)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wl_user_id ON watchlist_cpv(user_id)")


def _apply_v10_is_admin(conn: Any) -> None:
    """Añade columna is_admin a users si no existe (idempotente)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if not exists:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "is_admin" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
