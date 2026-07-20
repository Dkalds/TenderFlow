"""Dataclasses de dominio y operaciones de escritura sobre la BD.

Contiene los modelos ``Licitacion`` y ``Adjudicacion``, las constantes SQL
pre-computadas, y todas las funciones de upsert, historial y FTS.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields
from typing import Any

from config import HISTORY_TRACKED_FIELDS
from db.connection import connect, is_postgres_backend, now_utc_iso
from db.dlq import record_failure
from observability.logging import get_logger
from observability.runtime_metrics import upsert_rows_dropped_total

_log = get_logger(__name__)


# Constraint violations llegan como `sqlite3.IntegrityError` con sqlite3 stdlib
# y como `ValueError` con el driver libsql (Turso). Ambos llevan el mismo
# mensaje canónico de SQLite ("UNIQUE constraint failed: ...", etc.), así que
# se pueden clasificar igual por el texto.
_CONSTRAINT_EXC: tuple[type[BaseException], ...] = (sqlite3.IntegrityError, ValueError)


def _classify_integrity_error(exc: BaseException) -> str:
    """Clasifica una constraint violation de SQLite/libsql por el mensaje.

    Returns "unique" | "check" | "fk" | "notnull" | "other".

    Los mensajes de SQLite son estables y forman parte de su contrato público.
    Se usa para distinguir un dedup intra-XML legítimo (UNIQUE) de una pérdida
    real de datos (CHECK/FK/NOT NULL) que debe ir a la DLQ.
    """
    msg = str(exc).lower()
    if "unique" in msg:
        return "unique"
    if "check" in msg:
        return "check"
    if "foreign key" in msg:
        return "fk"
    if "not null" in msg:
        return "notnull"
    return "other"


def _earliest_iso_date(a: str | None, b: str | None) -> str | None:
    """Devuelve la fecha ISO (YYYY-MM-DD) más temprana, ignorando nulos.

    Las fechas ISO ordenan lexicográficamente igual que cronológicamente, así
    que ``min`` sobre strings es correcto. Se usa para que ``fecha_publicacion``
    conserve el primer anuncio del expediente y no retroceda/avance cuando una
    fase posterior (adjudicación, formalización) trae la fecha de SU anuncio.
    """
    if a is None:
        return b
    if b is None:
        return a
    return a if a <= b else b


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
    # Fuente de ingesta (ADR-009): 'placsp', 'ted', 'pscp_cat'… Las fuentes
    # nuevas namespacean ademas su id_externo como "{fuente}:{id_natural}".
    fuente: str = "placsp"
    fecha_extraccion: str = field(default_factory=now_utc_iso)


@dataclass
class DocumentoReferencia:
    """Referencia a un adjunto (pliego) de una licitación, extraída del CODICE.

    Plan Pliegos+RAG (F6): metadatos puros del parser — sin ``licitacion_id``
    (se resuelve en el punto de persistencia, junto al resto del batch) ni
    ``status``/``texto`` (los gestiona ``db/repositories/documentos.py`` tras
    la descarga/extracción, F7-F8). No es un dataclass SQL-mapeado 1:1 como
    ``Licitacion``/``Adjudicacion`` — ``documentos`` tiene columnas que el
    parser nunca conoce (``sha256``, ``storage_key``…).
    """

    tipo: str  # legal | technical | additional
    uri: str
    filename: str | None = None


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
        existing_pub: dict[str, str | None] = {}
        _CHUNK = 500
        for i in range(0, len(batch), _CHUNK):
            chunk = batch[i : i + _CHUNK]
            placeholders = ", ".join("?" for _ in chunk)
            chunk_ids = [lic.id_externo for lic in chunk]
            rows = c.execute(
                f"SELECT id_externo, fecha_publicacion FROM licitaciones "
                f"WHERE id_externo IN ({placeholders})",
                chunk_ids,
            ).fetchall()
            existing_pub.update((row[0], row[1]) for row in rows)

        for lic in batch:
            data = asdict(lic)
            if lic.id_externo in existing_pub:
                # No sobrescribir con una fecha de publicación posterior (fase
                # de adjudicación/formalización): conservar el primer anuncio.
                data["fecha_publicacion"] = _earliest_iso_date(
                    existing_pub[lic.id_externo], data["fecha_publicacion"]
                )
            vals = [data[k] for k in _LIC_KEYS]
            # Column names come from dataclass fields (controlled code) — safe
            c.execute(
                f"INSERT INTO licitaciones ({_LIC_COLS}) VALUES ({_LIC_PLACEHOLDERS}) "
                f"ON CONFLICT(id_externo) DO UPDATE SET {_LIC_UPDATES}",
                vals,
            )

    existing_ids = set(existing_pub)
    nuevas = sum(1 for lic in batch if lic.id_externo not in existing_ids)
    actualizadas = len(batch) - nuevas
    return nuevas, actualizadas


def replace_adjudicaciones(
    licitacion_id: str,
    items: Iterable[Adjudicacion],
    *,
    run_id: str | None = None,
    fuente: str = "unknown",
) -> tuple[int, int]:
    """Reemplaza todas las adjudicaciones de una licitación (idempotente).

    Cada fila se inserta dentro de su propio try/except. Una violación real
    de integridad (CHECK/FK/NOT NULL) NO aborta el resto del batch: la fila
    se enruta a la DLQ vía record_failure con scope="adjudicacion" y
    payload_ref="{licitacion_id}:{nif}:{importe_adjudicado}" para replay
    dirigido por dlq_retry.py. Un UNIQUE conflict (duplicado intra-XML sobre
    UNIQUE(licitacion_id, nif, importe_adjudicado)) se ignora como dedup
    benigno, sin DLQ ni métrica.

    Returns:
        Tuple of (persisted, dropped) — persistidas realmente y violaciones
        enrutadas a la DLQ. Los dedups UNIQUE NO se cuentan en dropped
        (son intencionales del patrón DELETE-then-insert).
    """
    items_list = list(items)
    persisted = 0
    dropped = 0
    failures: list[tuple[BaseException, str]] = []
    with connect() as c:
        c.execute("DELETE FROM adjudicaciones WHERE licitacion_id = ?", [licitacion_id])
        for adj in items_list:
            data = asdict(adj)
            vals = [data[k] for k in _ADJ_KEYS]
            # SAVEPOINT por fila: libsql/SQLite invalidan la transacción al
            # primer fallo de constraint, por lo que el INSERT directo
            # tumbaría todo el lote. El SAVEPOINT aísla cada intento.
            c.execute("SAVEPOINT adj_sp")
            try:
                c.execute(
                    f"INSERT INTO adjudicaciones ({_ADJ_COLS}) VALUES ({_ADJ_PLACEHOLDERS})",
                    vals,
                )
                c.execute("RELEASE SAVEPOINT adj_sp")
                persisted += 1
            except _CONSTRAINT_EXC as exc:
                c.execute("ROLLBACK TO SAVEPOINT adj_sp")
                c.execute("RELEASE SAVEPOINT adj_sp")
                # libsql mapea constraint violations a ValueError; descartamos
                # cualquier ValueError que no sea de constraint para no
                # tragarnos bugs genuinos.
                if "constraint" not in str(exc).lower():
                    raise
                kind = _classify_integrity_error(exc)
                if kind == "unique":
                    _log.debug(
                        "adj_dedup_unique",
                        licitacion_id=licitacion_id,
                        nif=adj.nif,
                    )
                else:
                    dropped += 1
                    upsert_rows_dropped_total.labels(table="adjudicaciones").inc()
                    _log.warning(
                        "upsert_row_dropped",
                        table="adjudicaciones",
                        licitacion_id=licitacion_id,
                        nif=adj.nif,
                        constraint=kind,
                    )
                    failures.append((exc, f"{licitacion_id}:{adj.nif}:{adj.importe_adjudicado}"))
    # Persistir failures fuera de la transacción del upsert para no
    # interferir con su lock; record_failure es best-effort.
    for caught_exc, payload_ref in failures:
        record_failure(run_id, fuente, caught_exc, scope="adjudicacion", payload_ref=payload_ref)
    return persisted, dropped


def replace_adjudicaciones_batch(
    adj_por_lic: dict[str, list[Adjudicacion]],
    *,
    run_id: str | None = None,
    fuente: str = "unknown",
) -> tuple[int, int, int]:
    """Reemplaza adjudicaciones para múltiples licitaciones en una sola transacción.

    Agrupa todos los DELETEs y INSERTs en un único ``connect()`` context
    (transacción), reduciendo la contención del lock de SQLite vs. el
    patrón N+1 de llamar ``replace_adjudicaciones`` por cada licitación.

    Cada INSERT está envuelto en su propio try/except: una violación de
    constraint NO aborta el resto del batch. Los UNIQUE se ignoran como
    dedup; las violaciones reales se enrutan a la DLQ con
    scope="adjudicacion".

    Returns:
        Tuple of (persisted, dropped, failed) — inserciones reales,
        violaciones de constraint enrutadas a la DLQ (sin contar dedups
        UNIQUE), y licitaciones con excepción no-IntegrityError (raras:
        connection, lock, etc.).
    """
    persisted = 0
    dropped = 0
    failed = 0
    failures: list[tuple[BaseException, str]] = []
    with connect() as c:
        for lic_id, adjs in adj_por_lic.items():
            try:
                c.execute(
                    "DELETE FROM adjudicaciones WHERE licitacion_id = ?",
                    [lic_id],
                )
                for adj in adjs:
                    data = asdict(adj)
                    vals = [data[k] for k in _ADJ_KEYS]
                    # SAVEPOINT por fila: necesario para que un fallo de
                    # constraint no tumbe el resto del batch en libsql.
                    c.execute("SAVEPOINT adj_sp")
                    try:
                        c.execute(
                            f"INSERT INTO adjudicaciones ({_ADJ_COLS}) VALUES ({_ADJ_PLACEHOLDERS})",
                            vals,
                        )
                        c.execute("RELEASE SAVEPOINT adj_sp")
                        persisted += 1
                    except _CONSTRAINT_EXC as exc:
                        c.execute("ROLLBACK TO SAVEPOINT adj_sp")
                        c.execute("RELEASE SAVEPOINT adj_sp")
                        if "constraint" not in str(exc).lower():
                            raise
                        kind = _classify_integrity_error(exc)
                        if kind == "unique":
                            _log.debug(
                                "adj_dedup_unique",
                                licitacion_id=lic_id,
                                nif=adj.nif,
                            )
                        else:
                            dropped += 1
                            upsert_rows_dropped_total.labels(table="adjudicaciones").inc()
                            _log.warning(
                                "upsert_row_dropped",
                                table="adjudicaciones",
                                licitacion_id=lic_id,
                                nif=adj.nif,
                                constraint=kind,
                            )
                            failures.append((exc, f"{lic_id}:{adj.nif}:{adj.importe_adjudicado}"))
            except Exception:
                failed += 1
    # Persistir failures fuera de la transacción del upsert (best-effort).
    for caught_exc, payload_ref in failures:
        record_failure(run_id, fuente, caught_exc, scope="adjudicacion", payload_ref=payload_ref)
    return persisted, dropped, failed


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
        # fecha_publicacion se pide como columna extra al final (fuera de
        # col_names) para conservar el primer anuncio sin alterar el snapshot
        # de historial (que solo cubre _HISTORY_SELECT_COLS).
        existing_rows = c.execute(
            f"SELECT {_HISTORY_SELECT_COLS}, fecha_publicacion FROM licitaciones "
            f"WHERE id_externo IN ({placeholders})",
            ids,
        ).fetchall()
        existing: dict[str, dict[str, Any]] = {
            row[0]: dict(zip(col_names, row, strict=False)) for row in existing_rows
        }
        existing_pub: dict[str, str | None] = {row[0]: row[-1] for row in existing_rows}

        for lic in chunk:
            data = asdict(lic)
            if lic.id_externo in existing_pub:
                # No sobrescribir con una fecha de publicación posterior (fase
                # de adjudicación/formalización): conservar el primer anuncio.
                data["fecha_publicacion"] = _earliest_iso_date(
                    existing_pub[lic.id_externo], data["fecha_publicacion"]
                )
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
    """True si la búsqueda de texto completo está disponible (FTS5 o search_vector)."""
    with connect() as c:
        if is_postgres_backend():
            row = c.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='licitaciones' AND column_name='search_vector' LIMIT 1"
            ).fetchone()
        else:
            row = c.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='licitaciones_fts'"
            ).fetchone()
        return row is not None


def search_fts(query: str, limit: int = 50, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    """Busca licitaciones usando FTS5/search_vector. Devuelve (rows, total)."""
    query = query.strip()
    if not query:
        return [], 0
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    with connect() as c:
        if is_postgres_backend():
            count_row = c.execute(
                "SELECT COUNT(*) FROM licitaciones "
                "WHERE search_vector @@ websearch_to_tsquery('spanish', ?)",
                [query],
            ).fetchone()
            total = int(count_row[0])
            cur = c.execute(
                "SELECT * FROM licitaciones "
                "WHERE search_vector @@ websearch_to_tsquery('spanish', ?) "
                "ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('spanish', ?)) DESC "
                "LIMIT ? OFFSET ?",
                [query, query, limit, offset],
            )
        else:
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
        rows = [
            {k: v for k, v in zip(cols, r, strict=False) if k != "search_vector"}
            for r in cur.fetchall()
        ]
    return rows, total
