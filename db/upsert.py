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


# Constraint violations llegan como `sqlite3.IntegrityError` con sqlite3 stdlib.
# Llevan el mensaje canónico de SQLite ("UNIQUE constraint failed: ...", etc.),
# así que se pueden clasificar igual por el texto.
def _constraint_exc_types() -> tuple[type[BaseException], ...]:
    """Excepciones que representan una violación de constraint, por driver.

    psycopg3 señala las violaciones con ``psycopg.errors.IntegrityError``, que
    **no** deriva de ``ValueError``. Sin incluirla, el ``except`` de
    ``replace_adjudicaciones`` no la capturaba y una sola fila inválida
    abortaba el lote entero de la licitación en vez de irse a la DLQ — con la
    transacción ya envenenada por Postgres. La suite no lo veía porque corría
    sobre SQLite (ADR-018).
    """
    types: list[type[BaseException]] = [sqlite3.IntegrityError, ValueError]
    try:
        import psycopg

        types.append(psycopg.errors.IntegrityError)
    except ImportError:  # pragma: no cover - psycopg es dependencia dura
        pass
    return tuple(types)


_CONSTRAINT_EXC: tuple[type[BaseException], ...] = _constraint_exc_types()


def _classify_integrity_error(exc: BaseException) -> str:
    """Clasifica una constraint violation por el mensaje del motor.

    Returns "unique" | "check" | "fk" | "notnull" | "other".

    Se usa para distinguir un dedup intra-XML legítimo (UNIQUE) de una pérdida
    real de datos (CHECK/FK/NOT NULL) que debe ir a la DLQ.

    Los mensajes de SQLite y de Postgres son estables y parte de su contrato
    público, pero **no coinciden**: donde SQLite dice ``NOT NULL constraint
    failed``, Postgres dice ``violates not-null constraint`` (con guion). Sin
    contemplar ambas grafías, una violación de NOT NULL en Postgres se
    clasificaba como ``other``.
    """
    msg = str(exc).lower()
    if "unique" in msg:
        return "unique"
    if "check" in msg:
        return "check"
    if "foreign key" in msg:
        return "fk"
    if "not null" in msg or "not-null" in msg:
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

        lic_rows: list[list[Any]] = []
        for lic in batch:
            data = asdict(lic)
            if lic.id_externo in existing_pub:
                # No sobrescribir con una fecha de publicación posterior (fase
                # de adjudicación/formalización): conservar el primer anuncio.
                data["fecha_publicacion"] = _earliest_iso_date(
                    existing_pub[lic.id_externo], data["fecha_publicacion"]
                )
            lic_rows.append([data[k] for k in _LIC_KEYS])

        # Un único executemany en vez de un execute por fila: contra una BD
        # remota lo que domina es el round trip, no el coste del INSERT
        # (psycopg3 agrupa el executemany en un solo viaje). Column names come
        # from dataclass fields (controlled code) — safe.
        if lic_rows:
            c.executemany(
                f"INSERT INTO licitaciones ({_LIC_COLS}) VALUES ({_LIC_PLACEHOLDERS}) "
                f"ON CONFLICT(id_externo) DO UPDATE SET {_LIC_UPDATES}",
                lic_rows,
            )

    existing_ids = set(existing_pub)
    nuevas = sum(1 for lic in batch if lic.id_externo not in existing_ids)
    actualizadas = len(batch) - nuevas
    return nuevas, actualizadas


def _dedup_adj_rows(
    licitacion_id: str, adjs: Iterable[Adjudicacion]
) -> list[tuple[Adjudicacion, list[Any]]]:
    """Deduplica en memoria por ``UNIQUE(licitacion_id, nif, importe_adjudicado)``.

    ``replace_*`` borra antes todas las filas de la licitación, así que el único
    conflicto UNIQUE posible es **intra-lote**: deduplicar aquí es equivalente a
    dejar que lo rechace el motor, y permite contar ``persisted`` sin depender
    del ``rowcount`` de ``executemany`` (poco fiable entre drivers).

    SQL trata NULL como distinto de NULL, así que una clave con cualquier
    componente NULL nunca conflictúa: esas filas **no** se deduplican, o se
    perderían adjudicaciones sin NIF que la BD sí acepta.
    """
    seen: set[tuple[Any, ...]] = set()
    out: list[tuple[Adjudicacion, list[Any]]] = []
    for adj in adjs:
        data = asdict(adj)
        key = (data["licitacion_id"], data["nif"], data["importe_adjudicado"])
        if None not in key:
            if key in seen:
                _log.debug("adj_dedup_unique", licitacion_id=licitacion_id, nif=adj.nif)
                continue
            seen.add(key)
        out.append((adj, [data[k] for k in _ADJ_KEYS]))
    return out


def _insert_adj_rowwise(
    c: Any,
    licitacion_id: str,
    rows: list[tuple[Adjudicacion, list[Any]]],
    failures: list[tuple[BaseException, str]],
) -> tuple[int, int]:
    """Inserta fila a fila aislando cada intento. Devuelve ``(persisted, dropped)``.

    Camino lento: sólo se recorre cuando el ``executemany`` del lote falló por
    una violación real de constraint, para identificar **qué** fila la causó y
    enrutarla a la DLQ. Un fallo no-constraint se propaga.
    """
    persisted = 0
    dropped = 0
    for adj, vals in rows:
        # SAVEPOINT por fila: Postgres invalida la transacción al primer fallo
        # de constraint, así que el INSERT directo tumbaría el resto del lote.
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
                _log.debug("adj_dedup_unique", licitacion_id=licitacion_id, nif=adj.nif)
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
    return persisted, dropped


def _try_insert_adj_batch(c: Any, rows: list[list[Any]]) -> bool:
    """Intenta insertar todas las filas en un solo ``executemany``.

    Devuelve ``True`` si el lote entró limpio. Si alguna fila viola una
    constraint, deshace el intento (``ROLLBACK TO SAVEPOINT``, que conserva el
    ``DELETE`` previo) y devuelve ``False`` para que el llamador recorra el
    camino fila a fila y aísle la culpable.
    """
    if not rows:
        return True
    c.execute("SAVEPOINT adj_batch")
    try:
        c.executemany(
            f"INSERT INTO adjudicaciones ({_ADJ_COLS}) VALUES ({_ADJ_PLACEHOLDERS}) "
            "ON CONFLICT DO NOTHING",
            rows,
        )
    except _CONSTRAINT_EXC:
        c.execute("ROLLBACK TO SAVEPOINT adj_batch")
        c.execute("RELEASE SAVEPOINT adj_batch")
        return False
    c.execute("RELEASE SAVEPOINT adj_batch")
    return True


def replace_adjudicaciones(
    licitacion_id: str,
    items: Iterable[Adjudicacion],
    *,
    run_id: str | None = None,
    fuente: str = "unknown",
) -> tuple[int, int]:
    """Reemplaza todas las adjudicaciones de una licitación (idempotente).

    El lote entra con un único ``executemany``. Si alguna fila viola una
    constraint real (CHECK/FK/NOT NULL) el intento se deshace y se reintenta
    fila a fila para aislar la culpable: esa fila NO aborta el resto, se enruta
    a la DLQ vía record_failure con scope="adjudicacion" y
    payload_ref="{licitacion_id}:{nif}:{importe_adjudicado}" para replay
    dirigido por dlq_retry.py. Un duplicado intra-lote sobre
    UNIQUE(licitacion_id, nif, importe_adjudicado) se deduplica antes de
    escribir, sin DLQ ni métrica.

    Returns:
        Tuple of (persisted, dropped) — persistidas realmente y violaciones
        enrutadas a la DLQ. Los dedups UNIQUE NO se cuentan en dropped
        (son intencionales del patrón DELETE-then-insert).
    """
    failures: list[tuple[BaseException, str]] = []
    with connect() as c:
        c.execute("DELETE FROM adjudicaciones WHERE licitacion_id = ?", [licitacion_id])
        rows = _dedup_adj_rows(licitacion_id, items)
        if _try_insert_adj_batch(c, [vals for _, vals in rows]):
            persisted, dropped = len(rows), 0
        else:
            persisted, dropped = _insert_adj_rowwise(c, licitacion_id, rows, failures)
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

    Camino rápido: un ``DELETE`` por chunk de licitaciones y **un solo
    ``executemany``** para todas las filas del lote, sin importar cuántas
    licitaciones traiga. Contra una BD remota lo que domina es el round trip,
    así que el coste pasa de O(filas) viajes a O(1).

    Si el lote choca con una constraint real se deshace y se reprocesa
    licitación a licitación (y dentro de cada una, fila a fila) para aislar la
    culpable: sólo se paga el coste del camino lento cuando hay algo que
    aislar. Los duplicados intra-lote se deduplican antes de escribir; las
    violaciones reales se enrutan a la DLQ con scope="adjudicacion".

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
        lic_ids = list(adj_por_lic)
        # DELETE agrupado, particionado para respetar el límite de parámetros
        # por sentencia (SQLITE_MAX_VARIABLE_NUMBER).
        _CHUNK = 500
        for i in range(0, len(lic_ids), _CHUNK):
            id_chunk = lic_ids[i : i + _CHUNK]
            placeholders = ", ".join("?" for _ in id_chunk)
            c.execute(
                f"DELETE FROM adjudicaciones WHERE licitacion_id IN ({placeholders})",
                id_chunk,
            )

        grupos = [(lic_id, _dedup_adj_rows(lic_id, adjs)) for lic_id, adjs in adj_por_lic.items()]
        todas = [vals for _, rows in grupos for _, vals in rows]

        if _try_insert_adj_batch(c, todas):
            persisted = len(todas)
        else:
            for lic_id, rows in grupos:
                try:
                    p, d = _insert_adj_rowwise(c, lic_id, rows, failures)
                    persisted += p
                    dropped += d
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

        lic_rows: list[list[Any]] = []
        history_rows: list[tuple[str, str, str, str, str]] = []

        for lic in chunk:
            data = asdict(lic)
            if lic.id_externo in existing_pub:
                # No sobrescribir con una fecha de publicación posterior (fase
                # de adjudicación/formalización): conservar el primer anuncio.
                data["fecha_publicacion"] = _earliest_iso_date(
                    existing_pub[lic.id_externo], data["fecha_publicacion"]
                )
            lic_rows.append([data[k] for k in _LIC_KEYS])
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
                    history_rows.append(
                        (
                            lic.id_externo,
                            now_utc_iso(),
                            source,
                            snapshot,
                            ",".join(changed),
                        )
                    )
                    result.modified.append(lic.id_externo)
                else:
                    result.unchanged.append(lic.id_externo)
            else:
                result.inserted.append(lic.id_externo)

        # Dos executemany (historial + licitaciones) en vez de hasta 2N execute.
        # El orden importa: el snapshot de historial debe escribirse con el
        # estado *anterior*, que se leyó arriba en `existing`, así que basta con
        # que ambos vayan en la misma transacción.
        if history_rows:
            c.executemany(
                "INSERT INTO licitaciones_history "
                "(id_externo, captured_at, source, snapshot_json, changed_fields) "
                "VALUES (?, ?, ?, ?, ?)",
                history_rows,
            )
        if lic_rows:
            c.executemany(
                f"INSERT INTO licitaciones ({_LIC_COLS}) VALUES ({_LIC_PLACEHOLDERS}) "
                f"ON CONFLICT(id_externo) DO UPDATE SET {_LIC_UPDATES}",
                lic_rows,
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
