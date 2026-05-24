"""Sistema simple de migraciones basado en tabla ``schema_version``.

Cada migración es una tupla ``(version, description, sql)``. Se aplican en
orden ascendente y la versión actual queda registrada en ``schema_version``.

Rollbacks: cada versión puede tener asociada una función ``down`` en
``ROLLBACKS`` que deshace los cambios. Se ejecutan en orden descendente.

.. deprecated::
   **Este módulo gestiona v1-v32 (sistema legado)**. El sistema de migraciones
   canónico del proyecto es **Alembic** (``db/alembic/``). Desde v22 en
   adelante, todas las migraciones nuevas se crean en Alembic.

   Plan de consolidación:
   - v1-v13: cubiertos por el baseline Alembic ``baseline001``
   - v14-v32: cubiertos por las migraciones Alembic v14-v22+
   - Este módulo se mantiene en modo lectura/compatibilidad para bases de datos
     existentes que todavía lo usen. No añadir nuevas migraciones aquí.

   Para nuevas migraciones: ``alembic revision --autogenerate -m "descripcion"``

.. note::

   Para bases de datos existentes sin Alembic, ejecutar ``apply_pending()``
   antes de ``alembic stamp head`` y luego ``alembic upgrade head``.
"""

from __future__ import annotations

from datetime import UTC, datetime
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
    (
        12,
        "rate_limits_table",
        """
        CREATE TABLE IF NOT EXISTS rate_limits (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            key     TEXT NOT NULL,
            ts      REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_rate_limits_expires
            ON rate_limits(key, ts)
        """,
    ),
    (
        13,
        "kpi_snapshots_table",
        """
        CREATE TABLE IF NOT EXISTS kpi_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            computed_at TEXT NOT NULL,
            metrica     TEXT NOT NULL,
            dimension   TEXT NOT NULL DEFAULT 'global',
            valor       REAL,
            valor_text  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_kpi_snapshots_fecha
            ON kpi_snapshots(computed_at DESC, metrica, dimension)
        """,
    ),
    (
        14,
        "add_tecnologia_column",
        """
        -- Columna añadida de forma programática en _apply_v14_tecnologia
        SELECT 1
        """,
    ),
    (
        15,
        "watchlist_frequency",
        """
        -- Columna añadida de forma programática en _apply_v15_frequency
        SELECT 1
        """,
    ),
    (
        16,
        "saved_filters_table",
        """
        CREATE TABLE IF NOT EXISTS saved_filters (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key        TEXT NOT NULL,
            name            TEXT NOT NULL,
            filters_json    TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            UNIQUE(user_key, name)
        );
        CREATE INDEX IF NOT EXISTS idx_saved_filters_user ON saved_filters(user_key);
        """,
    ),
    (
        17,
        "notification_reads_table",
        """
        CREATE TABLE IF NOT EXISTS notification_reads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key        TEXT NOT NULL,
            notification_id TEXT NOT NULL,
            read_at         TEXT NOT NULL,
            UNIQUE(user_key, notification_id)
        );
        CREATE INDEX IF NOT EXISTS idx_notif_reads_user ON notification_reads(user_key);
        """,
    ),
    (
        18,
        "pending_digests_and_audit_log",
        """
        CREATE TABLE IF NOT EXISTS pending_digests (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key        TEXT NOT NULL,
            recipient_email TEXT NOT NULL,
            entry_id        INTEGER NOT NULL,
            licitacion_id   TEXT NOT NULL,
            frequency       TEXT NOT NULL DEFAULT 'daily',
            matched_at      TEXT NOT NULL,
            sent            INTEGER NOT NULL DEFAULT 0,
            UNIQUE(entry_id, licitacion_id)
        );
        CREATE INDEX IF NOT EXISTS idx_pending_digests_recipient
            ON pending_digests(recipient_email, sent, frequency);

        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key        TEXT NOT NULL,
            session_hash    TEXT NOT NULL DEFAULT '',
            action          TEXT NOT NULL,
            detail          TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_key);
        CREATE INDEX IF NOT EXISTS idx_audit_log_action ON audit_log(action);
        """,
    ),
    (
        19,
        "api_keys_table",
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash    TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            last_used   TEXT,
            is_active   INTEGER NOT NULL DEFAULT 1,
            expires_at  TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash) WHERE is_active = 1;
        """,
    ),
    (
        20,
        "composite_indexes_ccaa_estado_fecha",
        # Los índices se aplican de forma programática en _apply_v20_indexes
        # porque SQLite no permite CREATE INDEX sobre una tabla que aún no existe
        # (en entornos de test la tabla licitaciones se crea via init_db, no aquí).
        "",
    ),
    (
        21,
        "api_keys_scopes_and_user_id",
        # Columnas añadidas programáticamente (SQLite no soporta IF NOT EXISTS en ALTER TABLE)
        "",
    ),
    (
        22,
        "webhook_deliveries_and_idempotency_keys",
        """
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            webhook_id   INTEGER NOT NULL,
            event_type   TEXT NOT NULL,
            status_code  INTEGER NOT NULL DEFAULT 0,
            success      INTEGER NOT NULL DEFAULT 0,
            payload_size INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            FOREIGN KEY(webhook_id) REFERENCES webhooks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_wh_del_webhook ON webhook_deliveries(webhook_id);
        CREATE INDEX IF NOT EXISTS idx_wh_del_created ON webhook_deliveries(created_at);

        CREATE TABLE IF NOT EXISTS idempotency_keys (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            idem_key      TEXT NOT NULL,
            endpoint      TEXT NOT NULL,
            response_json TEXT NOT NULL DEFAULT '{}',
            created_at    TEXT NOT NULL,
            UNIQUE(idem_key, endpoint)
        );
        CREATE INDEX IF NOT EXISTS idx_idem_key ON idempotency_keys(idem_key, endpoint);
        CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency_keys(created_at);
        """,
    ),
    (
        23,
        "ml_proba_column",
        # Columna añadida programáticamente en _apply_v23_ml_proba porque
        # SQLite no soporta IF NOT EXISTS en ALTER TABLE ADD COLUMN.
        "",
    ),
    (
        24,
        "cursor_composite_index",
        # Índice aplicado programáticamente en _apply_v24_cursor_index.
        "",
    ),
    (
        25,
        "api_keys_prefix_and_expiry",
        # Columnas prefix y expires_at añadidas programáticamente en _apply_v25_api_keys_prefix_expiry.
        "",
    ),
    (
        26,
        "audit_log_hash_chain",
        # Columnas prev_hash y this_hash en audit_log para inmutabilidad verificable.
        "",
    ),
    (
        27,
        "csp_violations_table",
        """
        CREATE TABLE IF NOT EXISTS csp_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            blocked_uri TEXT,
            violated_directive TEXT,
            document_uri TEXT,
            source_file TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_csp_created ON csp_violations(created_at);
        """,
    ),
    (
        28,
        "api_key_tiers",
        """
        CREATE TABLE IF NOT EXISTS api_key_tiers (
            tier TEXT PRIMARY KEY,
            daily_quota INTEGER NOT NULL DEFAULT 10000,
            per_minute_limit INTEGER NOT NULL DEFAULT 120,
            description TEXT
        );
        INSERT OR IGNORE INTO api_key_tiers (tier, daily_quota, per_minute_limit, description)
        VALUES
            ('free',       1000,  30,  'Tier gratuito - 1k req/dia, 30 req/min'),
            ('pro',        50000, 300, 'Tier pro - 50k req/dia, 300 req/min'),
            ('enterprise', 0,     0,   'Sin limites (0 = sin limite)');
        """,
    ),
    (
        29,
        "mat_aggregates",
        """
        CREATE TABLE IF NOT EXISTS mat_clusters (
            id_externo   TEXT PRIMARY KEY,
            cluster_id   INTEGER NOT NULL,
            cluster_label TEXT NOT NULL DEFAULT '',
            updated_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_mat_clusters_cluster_id
            ON mat_clusters(cluster_id);

        CREATE TABLE IF NOT EXISTS mat_top_empresas_ccaa (
            ccaa         TEXT NOT NULL,
            rank         INTEGER NOT NULL,
            nombre_canon TEXT NOT NULL,
            n_adj        INTEGER NOT NULL DEFAULT 0,
            importe_total REAL NOT NULL DEFAULT 0.0,
            updated_at   TEXT NOT NULL,
            PRIMARY KEY (ccaa, rank)
        );
        CREATE INDEX IF NOT EXISTS idx_mat_top_empresas_ccaa
            ON mat_top_empresas_ccaa(ccaa);
        """,
    ),
    (
        30,
        "ml_tecnologias_multilabel",
        """
        CREATE TABLE IF NOT EXISTS licitacion_tecnologia_score (
            licitacion_id      TEXT NOT NULL,
            tecnologia         TEXT NOT NULL,
            probabilidad       REAL NOT NULL,
            threshold_aplicado REAL NOT NULL,
            computed_at        TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (licitacion_id, tecnologia),
            FOREIGN KEY (licitacion_id) REFERENCES licitaciones(id_externo) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_lts_tecnologia
            ON licitacion_tecnologia_score(tecnologia, probabilidad DESC);
        CREATE INDEX IF NOT EXISTS idx_lts_lic
            ON licitacion_tecnologia_score(licitacion_id);
        -- Las columnas ml_tecnologias / ml_proba_max / ml_tech_principal se
        -- añaden de forma programática en _apply_v30_ml_tech_columns porque
        -- SQLite no soporta IF NOT EXISTS en ALTER TABLE ADD COLUMN.
        """,
    ),
    (
        31,
        "dlq_last_attempt_exhausted_columns",
        """
        -- last_attempt_at: timestamp del último intento (para backoff correcto).
        -- exhausted_at: timestamp en que se agotaron los reintentos (NULL = activo).
        -- Se añaden de forma programática en _apply_v31_dlq_columns porque
        -- SQLite no soporta IF NOT EXISTS en ALTER TABLE ADD COLUMN.
        """,
    ),
    (
        32,
        "performance_indexes",
        """
        -- Índices de rendimiento para consultas frecuentes.
        -- Se aplican programáticamente en _apply_v32_perf_indexes
        -- para tolerar la ausencia de tablas en entornos de test.
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

import re  # noqa: E402

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


# ---------------------------------------------------------------------------
# Rollbacks: SQL para deshacer cada migración (orden inverso)
# ---------------------------------------------------------------------------
# Regla: solo incluir rollbacks que sean seguros y reversibles.
# Las migraciones de tipo ALTER TABLE ADD COLUMN no son reversibles en SQLite
# (no soporta DROP COLUMN antes de SQLite 3.35), así que se marcan como tal.

ROLLBACKS: dict[int, str] = {
    1: """
        DROP INDEX IF EXISTS idx_fail_unresolved;
        DROP INDEX IF EXISTS idx_fail_run;
        DROP TABLE IF EXISTS failed_extractions;
        DROP INDEX IF EXISTS idx_runs_status;
        DROP INDEX IF EXISTS idx_runs_started;
        DROP TABLE IF EXISTS extraction_runs;
    """,
    2: """
        DROP INDEX IF EXISTS idx_wl_user;
        DROP TABLE IF EXISTS watchlist_cpv;
    """,
    # 3 y 4: ALTER TABLE ADD COLUMN — no reversible en SQLite < 3.35
    5: """
        DROP INDEX IF EXISTS idx_hist_externo;
        DROP TABLE IF EXISTS licitaciones_history;
        DROP TABLE IF EXISTS ingestion_cursors;
    """,
    # 6: ALTER TABLE ADD COLUMN — no reversible
    # 7: FTS5 + triggers
    7: """
        DROP TRIGGER IF EXISTS trg_fts_update_after;
        DROP TRIGGER IF EXISTS trg_fts_update;
        DROP TRIGGER IF EXISTS trg_fts_delete;
        DROP TRIGGER IF EXISTS trg_fts_insert;
        DROP TABLE IF EXISTS licitaciones_fts;
    """,
    8: """
        DROP INDEX IF EXISTS idx_users_oauth;
        DROP INDEX IF EXISTS idx_users_email;
        DROP TABLE IF EXISTS users;
    """,
    9: """
        DROP INDEX IF EXISTS idx_access_log_time;
        DROP INDEX IF EXISTS idx_access_log_user;
        DROP TABLE IF EXISTS access_log;
    """,
    # 10: ALTER TABLE ADD COLUMN — no reversible
    11: """
        DROP INDEX IF EXISTS idx_fail_unique_unresolved;
    """,
    12: """
        DROP INDEX IF EXISTS idx_rate_limits_expires;
        DROP TABLE IF EXISTS rate_limits;
    """,
    13: """
        DROP INDEX IF EXISTS idx_kpi_snapshots_fecha;
        DROP TABLE IF EXISTS kpi_snapshots;
    """,
    16: """
        DROP INDEX IF EXISTS idx_saved_filters_user;
        DROP TABLE IF EXISTS saved_filters;
    """,
    17: """
        DROP INDEX IF EXISTS idx_notif_reads_user;
        DROP TABLE IF EXISTS notification_reads;
    """,
    18: """
        DROP INDEX IF EXISTS idx_audit_log_action;
        DROP INDEX IF EXISTS idx_audit_log_user;
        DROP TABLE IF EXISTS audit_log;
        DROP INDEX IF EXISTS idx_pending_digests_recipient;
        DROP TABLE IF EXISTS pending_digests;
    """,
    19: """
        DROP INDEX IF EXISTS idx_api_keys_hash;
        DROP TABLE IF EXISTS api_keys;
    """,
    20: """
        DROP INDEX IF EXISTS idx_lic_estado_fecha;
        DROP INDEX IF EXISTS idx_lic_ccaa_fecha;
    """,
    32: """
        DROP INDEX IF EXISTS idx_lic_tecnologia;
        DROP INDEX IF EXISTS idx_lic_ml_proba;
        DROP INDEX IF EXISTS idx_adj_nombre_importe;
        DROP INDEX IF EXISTS idx_adj_ccaa_nombre;
    """,
}

# Migraciones que NO se pueden revertir (solo ADD COLUMN sin DROP COLUMN)
_IRREVERSIBLE_VERSIONS = {3, 4, 6, 10, 14, 15, 30}


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
            # Strip standalone comment lines so that a statement whose first
            # non-blank line is a comment is not silently skipped (bug: the
            # old `not stmt.startswith("--")` guard dropped the entire stmt).
            meaningful = "\n".join(
                line for line in stmt.splitlines() if not line.strip().startswith("--")
            ).strip()
            if meaningful:
                conn.execute(meaningful)
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
        # Migración 14: tecnologia column on licitaciones
        if version == 14:
            _apply_v14_tecnologia(conn)
        # Migración 15: frequency column on watchlist_cpv
        if version == 15:
            _apply_v15_frequency(conn)
        # Migración 20: índices compuestos en licitaciones
        if version == 20:
            _apply_v20_indexes(conn)
        # Migración 21: columnas scopes y user_id en api_keys
        if version == 21:
            _apply_v21_api_keys_columns(conn)
        # Migración 23: columna ml_proba en licitaciones
        if version == 23:
            _apply_v23_ml_proba(conn)
        # Migración 24: índice compuesto (fecha_publicacion DESC, id_externo) para cursor
        if version == 24:
            _apply_v24_cursor_index(conn)
        # Migración 25: columnas prefix y expires_at en api_keys
        if version == 25:
            _apply_v25_api_keys_prefix_expiry(conn)
        # Migración 26: columnas prev_hash y this_hash en audit_log
        if version == 26:
            _apply_v26_audit_hash_chain(conn)
        # Migración 27: tabla csp_violations — aplicada por SQL inline (no programática)
        # Migración 28: tabla api_key_tiers + columna tier en api_keys
        if version == 28:
            _apply_v28_api_key_tiers(conn)
        # Migración 30: columnas ml_tecnologias/ml_proba_max/ml_tech_principal
        if version == 30:
            _apply_v30_ml_tech_columns(conn)
        # Migración 31: columnas last_attempt_at y exhausted_at en failed_extractions
        if version == 31:
            _apply_v31_dlq_columns(conn)
        # Migración 32: índices de rendimiento (programático, tolera tablas ausentes)
        if version == 32:
            _apply_v32_perf_indexes(conn)
        conn.execute(
            "INSERT INTO schema_version (version, description, applied_at) VALUES (?, ?, ?)",
            (version, description, datetime.now(UTC).isoformat()),
        )
        applied.append(version)
    if applied:
        log.info("migrations_applied", versions=applied)
    return applied


def _apply_v6_columns(conn: Any) -> None:
    """Añade columnas extra a licitaciones si no existen (idempotente)."""
    for name, ctype in _V6_COLUMNS:
        if not _VALID_COLUMN_NAME.match(name):
            raise ValueError(f"Nombre de columna no válido: {name!r}")
        try:
            conn.execute(f"ALTER TABLE licitaciones ADD COLUMN {name} {ctype}")
        except Exception:
            log.warning("migration_step_error", version=6, column=name, exc_info=True)
            # Column already exists


def _apply_v20_indexes(conn: Any) -> None:
    """Crea índices compuestos en licitaciones si la tabla ya existe (idempotente)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='licitaciones'"
    ).fetchone()
    if not exists:
        return
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_ccaa_fecha ON licitaciones(ccaa, fecha_publicacion)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_estado_fecha ON licitaciones(estado, fecha_publicacion)"
    )


def _apply_v21_api_keys_columns(conn: Any) -> None:
    """Añade columnas scopes y user_id a api_keys si no existen (idempotente)."""
    try:
        conn.execute("ALTER TABLE api_keys ADD COLUMN scopes TEXT NOT NULL DEFAULT '*'")
    except Exception:
        log.warning("migration_step_error", version=21, column="scopes", exc_info=True)
    try:
        conn.execute("ALTER TABLE api_keys ADD COLUMN user_id INTEGER")
    except Exception:
        log.warning("migration_step_error", version=21, column="user_id", exc_info=True)


def _apply_v23_ml_proba(conn: Any) -> None:
    """Añade columna ml_proba a licitaciones si no existe (idempotente).

    Uses a try/except around ALTER TABLE instead of PRAGMA table_info
    checks because Turso/Hrana may return empty results for PRAGMA and
    sqlite_master queries inside transactions.
    """
    try:
        conn.execute("ALTER TABLE licitaciones ADD COLUMN ml_proba REAL")
    except Exception:
        # Column already exists — safe to ignore
        log.warning("migration_step_error", version=23, column="ml_proba", exc_info=True)


def _apply_v24_cursor_index(conn: Any) -> None:
    """Crea índice compuesto (fecha_publicacion DESC, id_externo) para cursor pagination.

    Este índice permite que las queries de cursor eviten full table scans
    en tablas grandes. Idempotente vía IF NOT EXISTS.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='licitaciones'"
    ).fetchone()
    if not exists:
        return
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_lic_fecha_id "
        "ON licitaciones(fecha_publicacion DESC, id_externo)"
    )


def _apply_v25_api_keys_prefix_expiry(conn: Any) -> None:
    """Añade columnas prefix y expires_at a api_keys si no existen (idempotente)."""
    try:
        conn.execute("ALTER TABLE api_keys ADD COLUMN prefix TEXT")
    except Exception:
        log.warning("migration_step_error", version=25, column="prefix", exc_info=True)
    try:
        conn.execute("ALTER TABLE api_keys ADD COLUMN expires_at TEXT")
    except Exception:
        log.warning("migration_step_error", version=25, column="expires_at", exc_info=True)


def _apply_v26_audit_hash_chain(conn: Any) -> None:
    """Añade columnas prev_hash y this_hash a audit_log para cadena de integridad."""
    try:
        conn.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
    except Exception:
        log.warning("migration_step_error", version=26, column="prev_hash", exc_info=True)
    try:
        conn.execute("ALTER TABLE audit_log ADD COLUMN this_hash TEXT")
    except Exception:
        log.warning("migration_step_error", version=26, column="this_hash", exc_info=True)


def _apply_v28_api_key_tiers(conn: Any) -> None:
    """Añade columna tier a api_keys con default 'free'.

    La tabla api_key_tiers ya fue creada por el SQL inline de la migración 28.
    Aquí solo se añade la FK-compatible column en api_keys.
    """
    try:
        conn.execute("ALTER TABLE api_keys ADD COLUMN tier TEXT NOT NULL DEFAULT 'free'")
    except Exception:
        log.warning("migration_step_error", version=28, column="tier", exc_info=True)


def _apply_v30_ml_tech_columns(conn: Any) -> None:
    """Añade columnas multi-tecnología a licitaciones (idempotente).

    ``ml_tecnologias``       — CSV de etiquetas predichas, ordenadas por probabilidad.
    ``ml_proba_max``         — Probabilidad máxima entre todas las tecnologías.
    ``ml_tech_principal``    — Etiqueta con mayor probabilidad (routing al equipo).

    ``ml_proba`` se mantiene intacta (= P(SAP)) por compatibilidad con el
    pipeline y dashboard existentes.
    """
    for stmt in (
        "ALTER TABLE licitaciones ADD COLUMN ml_tecnologias TEXT",
        "ALTER TABLE licitaciones ADD COLUMN ml_proba_max REAL",
        "ALTER TABLE licitaciones ADD COLUMN ml_tech_principal TEXT",
    ):
        try:
            conn.execute(stmt)
        except Exception:
            log.warning("migration_step_error", version=30, stmt=stmt[:60], exc_info=True)
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ml_tech_principal ON licitaciones(ml_tech_principal)"
        )
    except Exception:
        log.warning(
            "migration_step_error", version=30, operation="idx_ml_tech_principal", exc_info=True
        )


def _apply_v31_dlq_columns(conn: Any) -> None:
    """Añade columnas last_attempt_at y exhausted_at a failed_extractions (idempotente).

    ``last_attempt_at`` — timestamp del último intento de retry; usado para calcular
                          el backoff exponencial. Se inicializa con created_at.
    ``exhausted_at``    — timestamp en que la entrada alcanzó max_retries; NULL si activa.
    """
    for stmt in (
        "ALTER TABLE failed_extractions ADD COLUMN last_attempt_at TEXT",
        "ALTER TABLE failed_extractions ADD COLUMN exhausted_at TEXT",
    ):
        try:
            conn.execute(stmt)
        except Exception:
            log.warning("migration_step_error", version=31, stmt=stmt[:60], exc_info=True)
    # Inicializar last_attempt_at = created_at para entradas existentes
    try:
        conn.execute(
            "UPDATE failed_extractions "
            "SET last_attempt_at = created_at "
            "WHERE last_attempt_at IS NULL"
        )
    except Exception:
        log.warning(
            "migration_step_error", version=31, operation="backfill_last_attempt_at", exc_info=True
        )
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_fail_exhausted "
            "ON failed_extractions(exhausted_at) WHERE exhausted_at IS NOT NULL"
        )
    except Exception:
        log.warning(
            "migration_step_error", version=31, operation="idx_fail_exhausted", exc_info=True
        )


def _apply_v32_perf_indexes(conn: Any) -> None:
    """Crea índices de rendimiento en licitaciones y adjudicaciones (idempotente).

    Tolera la ausencia de tablas (entornos de test sin schema completo).
    """
    _INDEX_STMTS = [
        (
            "idx_lic_tecnologia",
            "CREATE INDEX IF NOT EXISTS idx_lic_tecnologia ON licitaciones(tecnologia)",
        ),
        (
            "idx_lic_ml_proba",
            "CREATE INDEX IF NOT EXISTS idx_lic_ml_proba ON licitaciones(ml_proba)",
        ),
        (
            "idx_adj_nombre_importe",
            "CREATE INDEX IF NOT EXISTS idx_adj_nombre_importe ON adjudicaciones(nombre, importe_adjudicado)",
        ),
        (
            "idx_adj_ccaa_nombre",
            "CREATE INDEX IF NOT EXISTS idx_adj_ccaa_nombre ON adjudicaciones(ccaa, nombre)",
        ),
    ]
    for name, stmt in _INDEX_STMTS:
        try:
            conn.execute(stmt)
        except Exception:
            log.warning("migration_step_error", version=32, operation=name, exc_info=True)


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
    try:
        conn.execute("ALTER TABLE watchlist_cpv ADD COLUMN user_id INTEGER REFERENCES users(id)")
    except Exception:
        log.warning("migration_step_error", version=8, column="user_id", exc_info=True)
    # Index for user_id lookups (idempotent via IF NOT EXISTS)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_wl_user_id ON watchlist_cpv(user_id)")


def _apply_v10_is_admin(conn: Any) -> None:
    """Añade columna is_admin a users si no existe (idempotente)."""
    try:
        conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
    except Exception:
        log.warning("migration_step_error", version=10, column="is_admin", exc_info=True)


def _apply_v14_tecnologia(conn: Any) -> None:
    """Añade columna tecnologia a licitaciones si no existe (idempotente).

    También backfill: marca licitaciones existentes con raw_keywords como 'SAP'
    ya que antes del multi-vendor solo se extraían licitaciones SAP.
    """
    try:
        conn.execute("ALTER TABLE licitaciones ADD COLUMN tecnologia TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tecnologia ON licitaciones(tecnologia)")
        # Backfill: todas las licitaciones existentes son SAP (pre multi-vendor)
        conn.execute("UPDATE licitaciones SET tecnologia = 'SAP' WHERE raw_keywords IS NOT NULL")
    except Exception:
        # Column already exists — index and backfill already applied
        log.warning("migration_step_error", version=14, column="tecnologia", exc_info=True)


def _apply_v15_frequency(conn: Any) -> None:
    """Añade columna frequency a watchlist_cpv si no existe (idempotente).

    Valores posibles: 'immediate' | 'daily' | 'weekly'. Default: 'daily'.
    """
    try:
        conn.execute("ALTER TABLE watchlist_cpv ADD COLUMN frequency TEXT NOT NULL DEFAULT 'daily'")
    except Exception:
        log.warning("migration_step_error", version=15, column="frequency", exc_info=True)


# ---------------------------------------------------------------------------
# Rollback: revertir migraciones hasta una versión objetivo
# ---------------------------------------------------------------------------


def rollback(target_version: int, conn: Any) -> list[int]:
    """Revierte migraciones desde la versión actual hasta ``target_version`` (inclusive).

    Args:
        target_version: Versión destino (se revertirán todas las versiones > target).
        conn: Conexión de base de datos activa.

    Returns:
        Lista de versiones revertidas en orden descendente.

    Raises:
        ValueError: Si se intenta revertir una migración irreversible.
        RuntimeError: Si target_version >= versión actual (nada que revertir).
    """
    _ensure_version_table(conn)
    current = current_version(conn)

    if target_version >= current:
        raise RuntimeError(
            f"No hay nada que revertir: versión actual={current}, destino={target_version}."
        )

    # Verificar que ninguna versión a revertir sea irreversible
    versions_to_revert = sorted(
        [v for v in ROLLBACKS if v > target_version and v <= current],
        reverse=True,
    )
    irreversible = [v for v in versions_to_revert if v in _IRREVERSIBLE_VERSIONS]
    if irreversible:
        raise ValueError(
            f"Las migraciones {irreversible} no son reversibles (ALTER TABLE ADD COLUMN). "
            f"Restaura desde un backup en su lugar."
        )

    reverted: list[int] = []
    for version in versions_to_revert:
        sql = ROLLBACKS.get(version, "")
        log.info("migration_rollback", version=version)
        for stmt in sql.split(";"):
            meaningful = "\n".join(
                line for line in stmt.splitlines() if not line.strip().startswith("--")
            ).strip()
            if meaningful:
                conn.execute(meaningful)
        conn.execute("DELETE FROM schema_version WHERE version = ?", (version,))
        reverted.append(version)

    if reverted:
        log.info("migrations_rolled_back", versions=reverted)
    return reverted


# ---------------------------------------------------------------------------
# Validación de integridad del esquema
# ---------------------------------------------------------------------------


def validate_schema(conn: Any) -> dict[str, bool]:
    """Verifica que las tablas principales y sus columnas clave existen.

    Returns:
        Dict {check_name: passed} — True si el check pasó.
    """
    checks: dict[str, bool] = {}

    def _table_exists(name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", [name]
        ).fetchone()
        return row is not None

    def _col_exists(table: str, col: str) -> bool:
        if not _table_exists(table):
            return False
        from db.database import get_table_columns

        cols = get_table_columns(conn, table)
        return col in cols

    # Tablas principales
    for table in ("licitaciones", "adjudicaciones", "extracciones", "schema_version"):
        checks[f"table_{table}"] = _table_exists(table)

    # Columnas críticas de licitaciones
    for col in ("id_externo", "titulo", "importe", "fecha_publicacion", "raw_keywords"):
        checks[f"licitaciones.{col}"] = _col_exists("licitaciones", col)

    # Migraciones opcionales (presencia de tablas de funcionalidades avanzadas)
    checks["fts5_available"] = _table_exists("licitaciones_fts")
    checks["history_available"] = _table_exists("licitaciones_history")
    checks["users_available"] = _table_exists("users")
    checks["rate_limits_available"] = _table_exists("rate_limits")
    checks["kpi_snapshots_available"] = _table_exists("kpi_snapshots")

    failed = [k for k, v in checks.items() if not v]
    if failed:
        log.warning("schema_validation_failed", failed=failed)
    else:
        log.info("schema_validation_passed", n_checks=len(checks))

    return checks
