"""Dataclasses de dominio y operaciones de escritura sobre la BD.

Contiene los modelos ``Licitacion`` y ``Adjudicacion``, las constantes SQL
pre-computadas, y todas las funciones de upsert, historial y FTS.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from config import HISTORY_TRACKED_FIELDS
from db.connection import connect, now_utc_iso

# ---------------------------------------------------------------------------
# Dataclasses de dominio
# ---------------------------------------------------------------------------


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
    # Multi-tech ML (poblado por scraper.tech_classifier). ml_proba se mantiene
    # como P(SAP) por compatibilidad; estos campos son aditivos.
    ml_tecnologias: str | None = None  # CSV ordenado por probabilidad
    ml_proba_max: float | None = None
    ml_tech_principal: str | None = None
    fecha_actualizacion_fuente: str | None = None
    fecha_extraccion: str = field(default_factory=now_utc_iso)


# ---------------------------------------------------------------------------
# Fragmentos SQL pre-computados (evitan recálculo por fila)
# ---------------------------------------------------------------------------

_LIC_KEYS = tuple(f.name for f in fields(Licitacion))
_LIC_COLS = ", ".join(_LIC_KEYS)
_LIC_PLACEHOLDERS = ", ".join("?" for _ in _LIC_KEYS)
_LIC_UPDATES = ", ".join(f"{k}=excluded.{k}" for k in _LIC_KEYS if k != "id_externo")

_ADJ_KEYS = tuple(f.name for f in fields(Adjudicacion))
_ADJ_COLS = ", ".join(_ADJ_KEYS)
_ADJ_PLACEHOLDERS = ", ".join("?" for _ in _ADJ_KEYS)

_HISTORY_SELECT_COLS = (
    "id_externo, titulo, descripcion, organo_contratacion, importe, "
    "estado, fecha_fin, fecha_inicio, duracion_valor, duracion_unidad"
)


# ---------------------------------------------------------------------------
# Operaciones de escritura
# ---------------------------------------------------------------------------


def upsert_licitaciones(items: Iterable[Licitacion]) -> tuple[int, int]:
    """Inserta o actualiza licitaciones. Devuelve (nuevas, actualizadas)."""
    batch = list(items)
    if not batch:
        return 0, 0

    with connect() as c:
        # Bulk SELECT para determinar qué IDs ya existen — evita N+1.
        # Particionado en grupos de 500 para respetar SQLITE_MAX_VARIABLE_NUMBER.
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
    items_list = list(items)
    with connect() as c:
        c.execute("DELETE FROM adjudicaciones WHERE licitacion_id = ?", [licitacion_id])
        n = 0
        for adj in items_list:
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
    """Registra una ejecución de extracción en la tabla ``extracciones``."""
    with connect() as c:
        c.execute(
            "INSERT INTO extracciones "
            "(fecha, fuente, nuevas, actualizadas, total_revisadas, notas) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (now_utc_iso(), fuente, nuevas, actualizadas, total, notas),
        )


def count_licitaciones() -> int:
    """Devuelve el número total de licitaciones en la BD."""
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

    def merge(self, other: UpsertResult) -> None:
        """Acumula resultados de otro UpsertResult en este."""
        self.inserted.extend(other.inserted)
        self.modified.extend(other.modified)
        self.unchanged.extend(other.unchanged)


def _upsert_chunk(
    chunk: list[Licitacion],
    source: str,
) -> UpsertResult:
    """Procesa un chunk de licitaciones en una sola transacción."""
    result = UpsertResult(inserted=[], modified=[], unchanged=[])

    col_names = [c.strip() for c in _HISTORY_SELECT_COLS.split(",")]
    with connect() as c:
        placeholders = ", ".join("?" for _ in chunk)
        ids = [lic.id_externo for lic in chunk]
        existing_rows = c.execute(
            f"SELECT {_HISTORY_SELECT_COLS} FROM licitaciones WHERE id_externo IN ({placeholders})",
            ids,
        ).fetchall()
        existing: dict[str, dict[str, Any]] = {
            row[0]: dict(zip(col_names, row, strict=False)) for row in existing_rows
        }

        for lic in chunk:
            data = asdict(lic)
            vals = [data[k] for k in _LIC_KEYS]
            old_record = existing.get(lic.id_externo)

            if old_record is not None:
                changed: list[str] = [
                    field_name
                    for field_name in HISTORY_TRACKED_FIELDS
                    if old_record.get(field_name) != data.get(field_name)
                ]

                if changed:
                    snapshot = json.dumps(old_record, ensure_ascii=False, default=str)
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

            c.execute(
                f"INSERT INTO licitaciones ({_LIC_COLS}) VALUES ({_LIC_PLACEHOLDERS}) "
                f"ON CONFLICT(id_externo) DO UPDATE SET {_LIC_UPDATES}",
                vals,
            )

    return result


def upsert_licitaciones_with_history(
    items: Iterable[Licitacion],
    source: str,
    *,
    chunk_size: int = 500,
) -> UpsertResult:
    """Inserta/actualiza licitaciones y registra cambios en licitaciones_history.

    Compara campos clave (HISTORY_TRACKED_FIELDS) con el registro existente.
    Si hay diff, guarda un snapshot del estado *anterior* en licitaciones_history.

    El batch se divide en chunks de ``chunk_size`` elementos, cada uno en su
    propia transacción SQLite, para liberar el write lock entre chunks y evitar
    bloqueos prolongados en backfills grandes.
    """
    result = UpsertResult(inserted=[], modified=[], unchanged=[])

    batch = list(items)
    if not batch:
        return result

    for i in range(0, len(batch), chunk_size):
        chunk = batch[i : i + chunk_size]
        chunk_result = _upsert_chunk(chunk, source)
        result.merge(chunk_result)

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


# ---------------------------------------------------------------------------
# Full-text search
# ---------------------------------------------------------------------------


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
