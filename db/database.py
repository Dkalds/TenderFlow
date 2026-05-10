"""Capa de persistencia SQLite / Turso (libSQL) para licitaciones."""

from __future__ import annotations

import json
import os
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


# ── Thread-local connection pool ────────────────────────────────────────────
_local = threading.local()


def _get_conn() -> Any:
    """Devuelve una conexión reutilizada por hilo (thread-local pool)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    if settings.TURSO_DATABASE_URL and settings.TURSO_AUTH_TOKEN:
        conn = libsql.connect(settings.TURSO_DATABASE_URL, auth_token=settings.TURSO_AUTH_TOKEN)
    else:
        # En CI (GitHub Actions y similares) NUNCA usar SQLite local: el FS es
        # efímero y los datos se perderían silenciosamente. Forzar fallo ruidoso.
        # Excepción: dentro de pytest (PYTEST_CURRENT_TEST lo fija pytest) se
        # permite SQLite temporal para el fixture tmp_db.
        if os.environ.get("CI", "").lower() in ("1", "true", "yes") and not os.environ.get(
            "PYTEST_CURRENT_TEST"
        ):
            raise RuntimeError(
                "Faltan TURSO_DATABASE_URL / TURSO_AUTH_TOKEN en el entorno CI. "
                "Configura los secrets del repositorio antes de ejecutar el pipeline."
            )
        conn = libsql.connect(str(settings.DB_PATH))
        # WAL mode: permite lecturas concurrentes del dashboard mientras el
        # scraper escribe. busy_timeout=5000ms evita "database is locked".
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.commit()
    _local.conn = conn
    return conn


def close_pool() -> None:
    """Cierra la conexión del hilo actual (para tests / shutdown)."""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            log.debug("connection_close_failed")
        _local.conn = None


@contextmanager
def connect() -> Iterator[Any]:
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    from config import ensure_data_dirs
    from db.migrations import apply_pending

    ensure_data_dirs()
    with connect() as c:
        for stmt in SCHEMA.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    c.execute(stmt)
                except Exception as exc:
                    log.error("init_db_schema_error", stmt=stmt[:120], error=str(exc))
                    raise
        try:
            apply_pending(c)
        except Exception as exc:
            log.error("init_db_migration_error", error=str(exc))
            raise


def upsert_licitaciones(items: Iterable[Licitacion]) -> tuple[int, int]:
    """Inserta o actualiza licitaciones. Devuelve (nuevas, actualizadas)."""
    batch = list(items)
    if not batch:
        return 0, 0

    with connect() as c:
        # Single bulk SELECT to determine which IDs already exist — avoids N+1
        placeholders = ", ".join("?" for _ in batch)
        ids = [lic.id_externo for lic in batch]
        existing_rows = c.execute(
            f"SELECT id_externo FROM licitaciones WHERE id_externo IN ({placeholders})",
            ids,
        ).fetchall()
        existing_ids = {row[0] for row in existing_rows}

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

    with connect() as c:
        for lic in items:
            existing = c.execute(
                "SELECT " + _HISTORY_SELECT_COLS + " FROM licitaciones WHERE id_externo = ?",
                [lic.id_externo],
            ).fetchone()

            data = asdict(lic)
            vals = [data[k] for k in _LIC_KEYS]

            if existing is not None:
                # Construir dict del registro existente para comparar
                col_names = [c.strip() for c in _HISTORY_SELECT_COLS.split(",")]
                old_record = dict(zip(col_names, existing, strict=False))

                # Detectar campos que cambiaron
                changed: list[str] = []
                for field_name in HISTORY_TRACKED_FIELDS:
                    old_val = old_record.get(field_name)
                    new_val = data.get(field_name)
                    # Normalizar para comparación (ambos None → iguales)
                    if old_val != new_val:
                        changed.append(field_name)

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
