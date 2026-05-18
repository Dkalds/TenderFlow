"""Capa de persistencia SQLite / Turso (libSQL) para licitaciones."""

from __future__ import annotations

import json
import os
import queue as _queue_mod
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from typing import Any

import libsql

from config import HISTORY_TRACKED_FIELDS, settings
from observability.logging import get_logger

log = get_logger(__name__)


def now_utc() -> datetime:
    """Devuelve datetime actual en UTC (aware). Reemplaza datetime.utcnow()."""
    return datetime.now(UTC)


def now_utc_iso() -> str:
    """ISO 8601 del instante actual en UTC."""
    return now_utc().isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS licitaciones (
    id_externo          TEXT PRIMARY KEY,
    titulo              TEXT NOT NULL,
    descripcion         TEXT,
    organo_contratacion TEXT,
    importe             REAL,
    moneda              TEXT DEFAULT 'EUR',
    cpv                 TEXT,
    tipo_contrato       TEXT,
    estado              TEXT,
    fecha_publicacion   TEXT,
    fecha_limite        TEXT,
    url                 TEXT,
    raw_keywords        TEXT,
    provincia           TEXT,
    ccaa                TEXT,
    nuts_code           TEXT,
    duracion_valor      REAL,
    duracion_unidad     TEXT,
    fecha_inicio        TEXT,
    fecha_fin           TEXT,
    prorroga_descripcion TEXT,
    ml_proba            REAL,
    tecnologia          TEXT,
    fecha_actualizacion_fuente TEXT,
    fecha_extraccion    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fecha_pub ON licitaciones(fecha_publicacion);
CREATE INDEX IF NOT EXISTS idx_organo    ON licitaciones(organo_contratacion);
CREATE INDEX IF NOT EXISTS idx_estado    ON licitaciones(estado);
CREATE INDEX IF NOT EXISTS idx_cpv       ON licitaciones(cpv);
CREATE INDEX IF NOT EXISTS idx_ccaa      ON licitaciones(ccaa);

CREATE TABLE IF NOT EXISTS adjudicaciones (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    licitacion_id           TEXT NOT NULL,
    nif                     TEXT,
    nombre                  TEXT NOT NULL,
    provincia               TEXT,
    ccaa                    TEXT,
    nuts_code               TEXT,
    importe_adjudicado      REAL,
    importe_pagable         REAL,
    fecha_adjudicacion      TEXT,
    es_pyme                 INTEGER,
    n_ofertas_recibidas     INTEGER,
    oferta_minima           REAL,
    oferta_maxima           REAL,
    result_code             TEXT,
    result_description      TEXT,
    fecha_extraccion        TEXT NOT NULL,
    UNIQUE(licitacion_id, nif, importe_adjudicado),
    FOREIGN KEY(licitacion_id) REFERENCES licitaciones(id_externo)
);
CREATE INDEX IF NOT EXISTS idx_adj_lic    ON adjudicaciones(licitacion_id);
CREATE INDEX IF NOT EXISTS idx_adj_nif    ON adjudicaciones(nif);
CREATE INDEX IF NOT EXISTS idx_adj_ccaa   ON adjudicaciones(ccaa);
CREATE INDEX IF NOT EXISTS idx_adj_fecha  ON adjudicaciones(fecha_adjudicacion);

CREATE TABLE IF NOT EXISTS extracciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha           TEXT NOT NULL,
    fuente          TEXT NOT NULL,
    nuevas          INTEGER DEFAULT 0,
    actualizadas    INTEGER DEFAULT 0,
    total_revisadas INTEGER DEFAULT 0,
    notas           TEXT
);
CREATE INDEX IF NOT EXISTS idx_extr_fecha ON extracciones(fecha);

CREATE TABLE IF NOT EXISTS ml_feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    expediente  TEXT NOT NULL,
    relevante   INTEGER NOT NULL,
    nota        TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_expediente ON ml_feedback(expediente);
CREATE INDEX IF NOT EXISTS idx_ml_feedback_created_at ON ml_feedback(created_at);

CREATE TABLE IF NOT EXISTS webhooks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT NOT NULL,
    url                 TEXT NOT NULL,
    secret              TEXT NOT NULL,
    event_types         TEXT NOT NULL,
    active              INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    last_triggered_at   TEXT,
    last_status         INTEGER,
    failure_count       INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_webhooks_active ON webhooks(active);

CREATE TABLE IF NOT EXISTS model_versions (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    name                     TEXT NOT NULL,
    version                  INTEGER NOT NULL,
    path                     TEXT NOT NULL,
    sha256                   TEXT NOT NULL,
    metrics_json             TEXT NOT NULL DEFAULT '{}',
    trained_at               TEXT NOT NULL,
    trained_on_n_samples     INTEGER,
    trained_on_n_feedbacks   INTEGER,
    is_active                INTEGER NOT NULL DEFAULT 0,
    notes                    TEXT,
    UNIQUE (name, version)
);
CREATE INDEX IF NOT EXISTS idx_model_versions_active ON model_versions(name, is_active);

CREATE TABLE IF NOT EXISTS totp_secrets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL UNIQUE,
    secret     TEXT NOT NULL,
    confirmed  INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_totp_user ON totp_secrets(user_id);

CREATE TABLE IF NOT EXISTS totp_recovery_codes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    code_hash  TEXT NOT NULL,
    used       INTEGER NOT NULL DEFAULT 0,
    used_at    TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_recovery_user ON totp_recovery_codes(user_id);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash  TEXT NOT NULL UNIQUE,
    user_id     INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    ip          TEXT,
    user_agent  TEXT,
    revoked     INTEGER NOT NULL DEFAULT 0,
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token   ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS feature_flags (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    enabled      INTEGER NOT NULL DEFAULT 0,
    rollout_pct  INTEGER NOT NULL DEFAULT 100,
    user_emails  TEXT NOT NULL DEFAULT '',
    description  TEXT,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feature_store (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    feature_name  TEXT NOT NULL,
    value_json    TEXT NOT NULL,
    version       TEXT NOT NULL DEFAULT 'v1',
    computed_at   TEXT NOT NULL,
    UNIQUE(entity_type, entity_id, feature_name, version)
);
CREATE INDEX IF NOT EXISTS idx_feature_store_entity ON feature_store(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_feature_store_name   ON feature_store(entity_type, feature_name);

CREATE TABLE IF NOT EXISTS domain_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    actor_id     INTEGER,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_domain_events_aggregate ON domain_events(aggregate_type, aggregate_id);
CREATE INDEX IF NOT EXISTS idx_domain_events_type      ON domain_events(event_type);
CREATE INDEX IF NOT EXISTS idx_domain_events_created   ON domain_events(created_at);
"""


@dataclass
class Adjudicacion:
    licitacion_id: str
    nombre: str
    nif: str | None = None
    provincia: str | None = None
    ccaa: str | None = None
    nuts_code: str | None = None
    importe_adjudicado: float | None = None
    importe_pagable: float | None = None
    fecha_adjudicacion: str | None = None
    es_pyme: int | None = None  # 0/1/None
    n_ofertas_recibidas: int | None = None
    oferta_minima: float | None = None
    oferta_maxima: float | None = None
    result_code: str | None = None
    result_description: str | None = None
    fecha_extraccion: str = field(default_factory=now_utc_iso)


@dataclass
class Licitacion:
    id_externo: str
    titulo: str
    descripcion: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    moneda: str = "EUR"
    cpv: str | None = None
    tipo_contrato: str | None = None
    estado: str | None = None
    fecha_publicacion: str | None = None
    fecha_limite: str | None = None
    url: str | None = None
    raw_keywords: str | None = None
    provincia: str | None = None
    ccaa: str | None = None
    nuts_code: str | None = None
    duracion_valor: float | None = None
    duracion_unidad: str | None = None  # ANN/MON/DAY
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    prorroga_descripcion: str | None = None
    ml_proba: float | None = None
    tecnologia: str | None = None  # SAP, SALESFORCE, ORACLE, MICROSOFT, etc.
    fecha_actualizacion_fuente: str | None = None
    fecha_extraccion: str = field(default_factory=now_utc_iso)


# --- Pre-computed SQL fragments (avoid per-row recalculation) ---------------
_LIC_KEYS = tuple(f.name for f in fields(Licitacion))
_LIC_COLS = ", ".join(_LIC_KEYS)
_LIC_PLACEHOLDERS = ", ".join("?" for _ in _LIC_KEYS)
_LIC_UPDATES = ", ".join(f"{k}=excluded.{k}" for k in _LIC_KEYS if k != "id_externo")

_ADJ_KEYS = tuple(f.name for f in fields(Adjudicacion))
_ADJ_COLS = ", ".join(_ADJ_KEYS)
_ADJ_PLACEHOLDERS = ", ".join("?" for _ in _ADJ_KEYS)


# ── Connection pool ─────────────────────────────────────────────────────────

_local = threading.local()

# Override para tests: si se setea, _get_conn() usa esta ruta en vez de settings.DB_PATH.
# Esto evita el patrón frágil de importlib.reload() en los tests.
_DB_PATH_OVERRIDE: str | None = None

# Pool de conexiones Turso (Queue thread-safe). Sólo se usa cuando hay
# TURSO_DATABASE_URL configurada (>1 conexión). Para SQLite local, thread-local basta.
_pool: _queue_mod.Queue[Any] | None = None
_pool_lock = threading.Lock()


def set_db_path_override(path: str | None) -> None:
    """Establece (o limpia con None) el override de ruta de BD para tests."""
    global _DB_PATH_OVERRIDE, _db_initialized
    _DB_PATH_OVERRIDE = path
    _db_initialized = False  # fuerza re-init en la nueva ruta


def is_turso_backend() -> bool:
    """Indica si la conexión activa apunta a Turso/Hrana (cloud o réplica).

    Centraliza la heurística usada en múltiples puntos del módulo. Devuelve
    ``False`` cuando hay un override de ruta de tests o cuando faltan
    credenciales de Turso (en cuyo caso se usa SQLite local).

    Importante: el protocolo Hrana no soporta sentencias ``PRAGMA``; usar
    esta función para decidir si emitirlas o no.
    """
    return bool(
        not _DB_PATH_OVERRIDE
        and settings.TURSO_DATABASE_URL
        and settings.TURSO_AUTH_TOKEN
    )


def safe_pragma(conn: Any, stmt: str) -> None:
    """Ejecuta un ``PRAGMA`` solo si el backend lo soporta (SQLite local).

    No-op en Turso/Hrana. Cualquier excepción se silencia (defensive): los
    PRAGMAs son optimizaciones, no deben romper la operación principal.
    """
    if is_turso_backend():
        return
    try:
        conn.execute(stmt)
    except Exception:
        log.debug("safe_pragma_failed", extra={"stmt": stmt})


def get_table_columns(conn: Any, table: str) -> set[str]:
    """Devuelve el conjunto de nombres de columna de ``table``.

    Funciona tanto en SQLite local (``PRAGMA table_info``) como en
    Turso/Hrana (fallback a ``SELECT * … LIMIT 0`` + ``cursor.description``).
    Devuelve conjunto vacío si la tabla no existe o no se puede inspeccionar.
    """
    # Intento 1: PRAGMA table_info (rápido en SQLite local)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
        if rows:
            return {r[1] for r in rows}
    except Exception:
        pass

    # Intento 2: cursor.description (Turso/Hrana, o PRAGMA devolvió vacío)
    try:
        cur = conn.execute(f"SELECT * FROM {table} LIMIT 0")  # noqa: S608
        if cur.description:
            return {d[0] for d in cur.description}
    except Exception:
        pass

    return set()


def _create_connection() -> Any:
    """Crea una nueva conexión a la BD según la configuración actual."""
    if is_turso_backend():
        return libsql.connect(settings.TURSO_DATABASE_URL, auth_token=settings.TURSO_AUTH_TOKEN)

    if (
        not _DB_PATH_OVERRIDE
        and os.environ.get("CI", "").lower() in ("1", "true", "yes")
        and not os.environ.get("PYTEST_CURRENT_TEST")
    ):
        raise RuntimeError(
            "Faltan TURSO_DATABASE_URL / TURSO_AUTH_TOKEN en el entorno CI. "
            "Configura los secrets del repositorio antes de ejecutar el pipeline."
        )
    db_path = _DB_PATH_OVERRIDE or str(settings.DB_PATH)
    conn = libsql.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.commit()
    return conn


def _health_check(conn: Any) -> bool:
    """Verifica que una conexión sigue viva."""
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def _get_conn() -> Any:
    """Devuelve una conexión reutilizada por hilo.

    Para Turso cloud usa un pool con health-check. Para SQLite local usa
    thread-local (1 conexión por hilo, WAL permite lecturas concurrentes).
    """
    global _pool

    # Para Turso con pool_size > 1, usar el pool compartido
    if is_turso_backend() and settings.DB_POOL_SIZE > 1:
        if _pool is None:
            with _pool_lock:
                if _pool is None:
                    _pool = _queue_mod.Queue(maxsize=settings.DB_POOL_SIZE)
        # Intentar obtener del pool
        try:
            conn = _pool.get_nowait()
            if _health_check(conn):
                return conn
            # Conexión muerta — crear nueva
            try:
                conn.close()
            except Exception:
                pass
        except _queue_mod.Empty:
            pass
        return _create_connection()

    # SQLite local / tests: thread-local (una conexión por hilo)
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    conn = _create_connection()
    _local.conn = conn
    return conn


def _return_conn(conn: Any) -> None:
    """Devuelve una conexión al pool (Turso) o la mantiene en thread-local."""
    if is_turso_backend() and settings.DB_POOL_SIZE > 1 and _pool is not None:
        try:
            _pool.put_nowait(conn)
        except _queue_mod.Full:
            try:
                conn.close()
            except Exception:
                pass


def close_pool() -> None:
    """Cierra la conexión del hilo actual y vacía el pool compartido."""
    global _pool
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            log.debug("connection_close_failed")
        _local.conn = None

    # Vaciar pool compartido (Turso)
    if _pool is not None:
        while not _pool.empty():
            try:
                c = _pool.get_nowait()
                c.close()
            except Exception:
                pass
        _pool = None


@contextmanager
def connect() -> Iterator[Any]:
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _return_conn(conn)


@contextmanager
def connect_read() -> Iterator[Any]:
    """Context manager de conexión de SOLO LECTURA.

    Si ``TURSO_REPLICA_URL`` está configurado, conecta a la réplica Turso
    (conexión efímera, sin pool). En caso contrario, delega en ``connect()``
    normal (misma BD, modo read-only via PRAGMA).
    """
    from config import settings

    replica_url = settings.TURSO_REPLICA_URL
    if replica_url:
        try:
            import libsql_experimental as libsql  # type: ignore[import-not-found]

            conn = libsql.connect(
                replica_url,
                auth_token=settings.TURSO_AUTH_TOKEN,
            )
            try:
                yield conn
            finally:
                conn.close()
            return
        except ImportError:
            pass  # fallback to local connect

    # Fallback: usar pool normal (sin pragma para Turso/Hrana)
    conn = _get_conn()
    try:
        safe_pragma(conn, "PRAGMA query_only = ON")
        yield conn
    finally:
        safe_pragma(conn, "PRAGMA query_only = OFF")
        _return_conn(conn)


_db_initialized = False


def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return
    from config import ensure_data_dirs
    from db.migrations import apply_pending

    ensure_data_dirs()
    with connect() as c:
        for stmt in SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                c.execute(stmt)
        apply_pending(c)
        _ensure_licitaciones_columns(c)
    _db_initialized = True


def _ensure_licitaciones_columns(conn: Any) -> None:
    """Ensure all Licitacion dataclass columns exist in the table.

    Defence-in-depth: on Turso/Hrana, ``PRAGMA table_info`` and
    ``sqlite_master`` may behave differently than local SQLite, causing
    programmatic migrations to silently skip ``ALTER TABLE`` statements.
    This function adds any missing columns directly.
    """
    expected = {f.name for f in fields(Licitacion)}
    existing = get_table_columns(conn, "licitaciones")
    if not existing:
        return
    missing = expected - existing
    # Column type mapping from the dataclass field annotations
    _TYPE_MAP: dict[type | str, str] = {
        float: "REAL",
        int: "INTEGER",
    }
    for col in sorted(missing):
        # Determine SQL type from the dataclass field
        fld = next((f for f in fields(Licitacion) if f.name == col), None)
        if fld is None:
            continue
        origin = getattr(fld.type, "__origin__", None) if hasattr(fld.type, "__origin__") else None
        base = getattr(fld.type, "__args__", (fld.type,))[0] if origin else fld.type
        sql_type = _TYPE_MAP.get(base, "TEXT")
        try:
            conn.execute(f"ALTER TABLE licitaciones ADD COLUMN {col} {sql_type}")
            log.info("ensure_column_added", column=col, sql_type=sql_type)
        except Exception:
            # Column may already exist (race) or name is invalid
            log.debug("ensure_column_skip", column=col)


def upsert_licitaciones(items: Iterable[Licitacion]) -> tuple[int, int]:
    """Inserta o actualiza licitaciones. Devuelve (nuevas, actualizadas)."""
    batch = list(items)
    if not batch:
        return 0, 0

    with connect() as c:
        # Bulk SELECT to determine which IDs already exist — avoids N+1.
        # Chunked in groups of 500 to stay within SQLite's SQLITE_MAX_VARIABLE_NUMBER.
        existing_ids: set[str] = set()
        _CHUNK = 500
        for i in range(0, len(batch), _CHUNK):
            chunk = batch[i : i + _CHUNK]
            placeholders = ", ".join("?" for _ in chunk)
            chunk_ids = [lic.id_externo for lic in chunk]
            rows = c.execute(
                f"SELECT id_externo FROM licitaciones WHERE id_externo IN ({placeholders})",
                chunk_ids,
            ).fetchall()
            existing_ids.update(row[0] for row in rows)

        for lic in batch:
            data = asdict(lic)
            vals = [data[k] for k in _LIC_KEYS]
            # Column names come from dataclass fields (controlled code) — safe
            c.execute(
                f"INSERT INTO licitaciones ({_LIC_COLS}) VALUES ({_LIC_PLACEHOLDERS}) "
                f"ON CONFLICT(id_externo) DO UPDATE SET {_LIC_UPDATES}",
                vals,
            )

    nuevas = sum(1 for lic in batch if lic.id_externo not in existing_ids)
    actualizadas = len(batch) - nuevas
    return nuevas, actualizadas


def replace_adjudicaciones(licitacion_id: str, items: Iterable[Adjudicacion]) -> int:
    """Reemplaza todas las adjudicaciones de una licitación (idempotente)."""
    items = list(items)
    with connect() as c:
        c.execute("DELETE FROM adjudicaciones WHERE licitacion_id = ?", [licitacion_id])
        n = 0
        for adj in items:
            data = asdict(adj)
            vals = [data[k] for k in _ADJ_KEYS]
            # Column names come from dataclass fields (controlled code) — safe
            c.execute(
                f"INSERT OR IGNORE INTO adjudicaciones ({_ADJ_COLS}) VALUES ({_ADJ_PLACEHOLDERS})",
                vals,
            )
            n += 1
    return n


def log_extraccion(
    fuente: str, nuevas: int, actualizadas: int, total: int, notas: str = ""
) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO extracciones "
            "(fecha, fuente, nuevas, actualizadas, total_revisadas, notas) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now_utc_iso(), fuente, nuevas, actualizadas, total, notas),
        )


def count_licitaciones() -> int:
    with connect() as c:
        row = c.execute("SELECT COUNT(*) FROM licitaciones").fetchone()
        return int(row[0])


# ---------------------------------------------------------------------------
# Cursor helpers (ingestion_cursors)
# ---------------------------------------------------------------------------


def get_cursor(source: str) -> dict[str, Any] | None:
    """Devuelve el cursor para una fuente de ingesta, o None si no existe."""
    with connect() as c:
        row = c.execute(
            "SELECT source, last_seen_updated, last_entry_id, etag, "
            "last_modified, updated_at "
            "FROM ingestion_cursors WHERE source = ?",
            [source],
        ).fetchone()
    if row is None:
        return None
    return {
        "source": row[0],
        "last_seen_updated": row[1],
        "last_entry_id": row[2],
        "etag": row[3],
        "last_modified": row[4],
        "updated_at": row[5],
    }


def set_cursor(
    source: str,
    *,
    last_seen_updated: str | None = None,
    last_entry_id: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    """Crea o actualiza el cursor de una fuente de ingesta."""
    now = now_utc_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO ingestion_cursors "
            "(source, last_seen_updated, last_entry_id, etag, last_modified, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source) DO UPDATE SET "
            "last_seen_updated = excluded.last_seen_updated, "
            "last_entry_id = excluded.last_entry_id, "
            "etag = excluded.etag, "
            "last_modified = excluded.last_modified, "
            "updated_at = excluded.updated_at",
            (source, last_seen_updated, last_entry_id, etag, last_modified, now),
        )


# ---------------------------------------------------------------------------
# Upsert con historial de cambios
# ---------------------------------------------------------------------------

_HISTORY_SELECT_COLS = (
    "id_externo, titulo, descripcion, organo_contratacion, importe, "
    "estado, fecha_fin, fecha_inicio, duracion_valor, duracion_unidad"
)


@dataclass
class UpsertResult:
    inserted: list[str]
    modified: list[str]
    unchanged: list[str]

    @property
    def nuevas(self) -> int:
        return len(self.inserted)

    @property
    def actualizadas(self) -> int:
        return len(self.modified) + len(self.unchanged)


def upsert_licitaciones_with_history(
    items: Iterable[Licitacion],
    source: str,
) -> UpsertResult:
    """Inserta/actualiza licitaciones y registra cambios en licitaciones_history.

    Compara campos clave (HISTORY_TRACKED_FIELDS) con el registro existente.
    Si hay diff, guarda un snapshot del estado *anterior* en licitaciones_history.
    """
    result = UpsertResult(inserted=[], modified=[], unchanged=[])

    batch = list(items)
    if not batch:
        return result

    # Bulk pre-fetch: un único SELECT IN (...) en lugar de N SELECTs individuales
    col_names = [c.strip() for c in _HISTORY_SELECT_COLS.split(",")]
    with connect() as c:
        placeholders = ", ".join("?" for _ in batch)
        ids = [lic.id_externo for lic in batch]
        existing_rows = c.execute(
            f"SELECT {_HISTORY_SELECT_COLS} FROM licitaciones WHERE id_externo IN ({placeholders})",
            ids,
        ).fetchall()
        # Construir dict {id_externo: old_record} para lookup O(1) por item
        existing: dict[str, dict[str, Any]] = {
            row[0]: dict(zip(col_names, row, strict=False)) for row in existing_rows
        }

        for lic in batch:
            data = asdict(lic)
            vals = [data[k] for k in _LIC_KEYS]
            old_record = existing.get(lic.id_externo)

            if old_record is not None:
                # Detectar campos que cambiaron
                changed: list[str] = [
                    field_name
                    for field_name in HISTORY_TRACKED_FIELDS
                    if old_record.get(field_name) != data.get(field_name)
                ]

                if changed:
                    # Guardar snapshot del estado ANTERIOR
                    snapshot = json.dumps(old_record, ensure_ascii=False, default=str)
                    # Limitar tamaño del snapshot para prevenir almacenamiento
                    # excesivo por payloads maliciosos en el feed
                    if len(snapshot) > 50_000:
                        snapshot = snapshot[:50_000] + "...(truncado)"
                    c.execute(
                        "INSERT INTO licitaciones_history "
                        "(id_externo, captured_at, source, snapshot_json, changed_fields) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            lic.id_externo,
                            now_utc_iso(),
                            source,
                            snapshot,
                            ",".join(changed),
                        ),
                    )
                    result.modified.append(lic.id_externo)
                else:
                    result.unchanged.append(lic.id_externo)
            else:
                result.inserted.append(lic.id_externo)

            # UPSERT (siempre, incluso si unchanged — actualiza fecha_extraccion)
            c.execute(
                f"INSERT INTO licitaciones ({_LIC_COLS}) VALUES ({_LIC_PLACEHOLDERS}) "
                f"ON CONFLICT(id_externo) DO UPDATE SET {_LIC_UPDATES}",
                vals,
            )

    return result


def get_history(id_externo: str, limit: int = 50) -> list[dict[str, Any]]:
    """Devuelve el historial de cambios de una licitación."""
    limit = max(1, min(limit, 1000))  # clamp to [1, 1000]
    with connect() as c:
        cur = c.execute(
            "SELECT id, id_externo, captured_at, source, snapshot_json, changed_fields "
            "FROM licitaciones_history "
            "WHERE id_externo = ? "
            "ORDER BY captured_at DESC LIMIT ?",
            [id_externo, limit],
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def fts_available() -> bool:
    """True si la tabla FTS5 existe en la BD."""
    with connect() as c:
        row = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='licitaciones_fts'"
        ).fetchone()
        return row is not None


def search_fts(query: str, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Busca licitaciones usando FTS5. Devuelve (rows, total)."""
    query = query.strip()
    if not query:
        return [], 0
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with connect() as c:
        count_row = c.execute(
            "SELECT COUNT(*) FROM licitaciones_fts WHERE licitaciones_fts MATCH ?",
            [query],
        ).fetchone()
        total = int(count_row[0])

        cur = c.execute(
            "SELECT l.* FROM licitaciones l "
            "JOIN licitaciones_fts f ON l.rowid = f.rowid "
            "WHERE licitaciones_fts MATCH ? "
            "ORDER BY rank LIMIT ? OFFSET ?",
            [query, limit, offset],
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]
    return rows, total
