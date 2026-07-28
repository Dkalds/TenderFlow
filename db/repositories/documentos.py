"""Repository para ``documentos``/``documento_chunks`` (plan Pliegos+RAG, F6).

Metadatos + texto extraído de los adjuntos (pliegos) de una licitación —
v56 (``db/alembic/versions/v56_pg_documentos_pgvector.py`` / equivalente
SQLite en ``db/schema.py``). Ciclo de vida por fila: ``pending`` (metadatos
insertados por el parser) → ``downloaded``/``error`` (F7, descarga) →
``extracted`` (F7, texto extraído) → chunks + embeddings (F8).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from db.database import DocumentoReferencia, connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)

_MAX_ERROR_DETAIL_LEN = 2000


def _to_pg_vector_literal(vec: Sequence[float]) -> str:
    """Formato de texto que pgvector castea con ``::vector`` (``[0.1,0.2,...]``)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class DocumentosRepository:
    """Acceso a la tabla ``documentos`` (TID251: SQL nuevo solo aquí)."""

    def upsert_meta(self, licitacion_id: str, refs: list[DocumentoReferencia]) -> int:
        """Inserta metadatos de documentos nuevos para una licitación.

        Idempotente sobre ``UNIQUE(licitacion_id, uri)``: re-ingestar la misma
        licitación (re-scrape diario) no duplica ni resetea el ``status`` de
        documentos ya procesados — ``ON CONFLICT DO NOTHING`` deja intacta
        cualquier fila existente. Devuelve el número de referencias procesadas
        (no distingue insertadas de ya-existentes: el driver libsql no
        garantiza un ``rowcount`` fiable tras ``executemany`` con conflicto).
        """
        if not refs:
            return 0
        rows = [(licitacion_id, r.tipo, r.uri, r.filename) for r in refs]
        with connect() as c:
            c.executemany(
                "INSERT INTO documentos (licitacion_id, tipo, uri, filename) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(licitacion_id, uri) DO NOTHING",
                rows,
            )
        return len(rows)

    def list_pendientes(self, limit: int = 100) -> list[dict[str, Any]]:
        """Documentos con ``status='pending'``, los más antiguos primero (FIFO)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, licitacion_id, tipo, uri, filename, content_type, size_bytes "
                "FROM documentos WHERE status = 'pending' "
                "ORDER BY created_at LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            )
            return rows_to_dicts(cur)

    def list_by_licitacion(self, licitacion_id: str) -> list[dict[str, Any]]:
        """Metadatos de los documentos de una licitación, para mostrarlos en el
        detalle de la UI (bloque "Documentos"). Excluye ``texto`` (puede ser
        muy pesado y solo lo usa el pipeline RAG internamente)."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, tipo, uri, filename, content_type, size_bytes, "
                "status, created_at FROM documentos WHERE licitacion_id = ? "
                "ORDER BY created_at",
                (licitacion_id,),
            )
            return rows_to_dicts(cur)

    def mark_downloaded(
        self,
        documento_id: int,
        *,
        filename: str | None,
        content_type: str | None,
        size_bytes: int | None,
        sha256: str | None,
    ) -> None:
        """Descarga completada — metadatos del binario, texto aún pendiente."""
        with connect() as c:
            c.execute(
                "UPDATE documentos SET status = 'downloaded', filename = ?, "
                "content_type = ?, size_bytes = ?, sha256 = ?, fetched_at = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    filename,
                    content_type,
                    size_bytes,
                    sha256,
                    now_utc_iso(),
                    now_utc_iso(),
                    documento_id,
                ),
            )

    def mark_extracted(self, documento_id: int, *, texto: str, sha256: str) -> None:
        """Texto extraído con éxito. ``sha256`` es del binario descargado —
        usado por el job de embeddings (F8) para saber si el contenido cambió
        entre corridas (skip si el hash no varió, delete+reinsert si sí)."""
        with connect() as c:
            c.execute(
                "UPDATE documentos SET status = 'extracted', texto = ?, sha256 = ?, "
                "fetched_at = ?, updated_at = ? WHERE id = ?",
                (texto, sha256, now_utc_iso(), now_utc_iso(), documento_id),
            )

    def mark_error(self, documento_id: int, *, error_detail: str) -> None:
        """Descarga o extracción fallida — no rompe el resto del batch."""
        with connect() as c:
            c.execute(
                "UPDATE documentos SET status = 'error', error_detail = ?, "
                "updated_at = ? WHERE id = ?",
                (error_detail[:_MAX_ERROR_DETAIL_LEN], now_utc_iso(), documento_id),
            )

    def get(self, documento_id: int) -> dict[str, Any] | None:
        """Fila completa por id (incluye ``texto``) — usado por el job de embeddings."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, licitacion_id, tipo, uri, filename, content_type, "
                "size_bytes, sha256, texto, status, error_detail, storage_key, "
                "fetched_at, created_at, updated_at FROM documentos WHERE id = ?",
                (documento_id,),
            )
            rows = rows_to_dicts(cur)
            return rows[0] if rows else None

    # ── documento_chunks (F8: chunking + embeddings) ────────────────────

    def list_extracted_without_chunks(self, limit: int = 50) -> list[dict[str, Any]]:
        """Documentos con texto extraído que aún no tienen chunks generados.

        Selección deliberadamente simple ("sin chunks" = candidato): en el
        pipeline actual (F6/F7) un documento pasa por ``extracted`` una sola
        vez — no hay camino de re-extracción que cambie ``texto`` después.
        Por eso la idempotencia entre corridas la da esta misma condición
        (`NOT EXISTS`): un documento ya chunkeado nunca vuelve a aparecer
        aquí, así que el job nunca reprocesa trabajo ya hecho.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, licitacion_id, texto FROM documentos "
                "WHERE status = 'extracted' "
                "AND id NOT IN (SELECT DISTINCT documento_id FROM documento_chunks) "
                "ORDER BY updated_at LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            )
            return rows_to_dicts(cur)

    def replace_chunks(self, documento_id: int, chunks: list[str], embeddings: Any) -> int:
        """Reemplaza (delete+insert) los chunks+embeddings de un documento.

        ``embeddings`` es indexable fila a fila (``np.ndarray`` de shape
        (n, dim) o lista de vectores), alineado 1:1 con ``chunks``.

        Transaccional dentro de una sola conexión: el DELETE corre primero,
        así que un fallo a mitad de los INSERTs no deja un estado "medio
        chunkeado" que pase el filtro `NOT EXISTS` de
        ``list_extracted_without_chunks`` — la siguiente corrida reintenta el
        documento completo desde cero (delete+reinsert es idempotente frente
        a reintentos, cumple el mismo contrato que pedía comparar por sha256
        sin necesitar una columna nueva en el schema).
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks ({len(chunks)}) y embeddings ({len(embeddings)}) "
                "deben tener la misma longitud"
            )

        with connect() as c:
            c.execute("DELETE FROM documento_chunks WHERE documento_id = ?", (documento_id,))
            if not chunks:
                return 0
            rows = [
                (documento_id, i, texto, _to_pg_vector_literal(emb))
                for i, (texto, emb) in enumerate(zip(chunks, embeddings, strict=True))
            ]
            c.executemany(
                "INSERT INTO documento_chunks (documento_id, chunk_index, texto, embedding) "
                "VALUES (?, ?, ?, ?::vector)",
                rows,
            )
        return len(chunks)

    # ── Lectura para el contexto LLM (resumen IA + chat contextualizado) ─
    # ``list_by_licitacion`` (más arriba) sirve tanto al bloque Documentos de
    # la UI como al contexto del asistente IA.

    def list_chunks_by_licitacion(
        self, licitacion_id: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Chunks de pliego de una licitación en orden documental.

        Orden: legal → technical → additional, y dentro de cada documento por
        ``chunk_index``. El ranking semántico frente a una pregunta se hace en
        Python (``services/rag/context.py``) — aquí no se consulta el embedding
        persistido, así que el mismo SQL sirve en Postgres y SQLite.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT dc.documento_id, d.tipo, d.filename, dc.chunk_index, dc.texto "
                "FROM documento_chunks dc JOIN documentos d ON d.id = dc.documento_id "
                "WHERE d.licitacion_id = ? "
                "ORDER BY CASE d.tipo WHEN 'legal' THEN 0 WHEN 'technical' THEN 1 ELSE 2 END, "
                "dc.documento_id, dc.chunk_index LIMIT ?",
                (licitacion_id, max(1, min(int(limit), 1000))),
            )
            return rows_to_dicts(cur)

    def list_textos_by_licitacion(
        self, licitacion_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Texto completo de los documentos ya extraídos de una licitación.

        Fallback para licitaciones cuyo texto está extraído pero el job de
        chunking aún no corrió (``documento_chunks`` vacío).
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, tipo, filename, texto FROM documentos "
                "WHERE licitacion_id = ? AND status = 'extracted' AND texto IS NOT NULL "
                "ORDER BY CASE tipo WHEN 'legal' THEN 0 WHEN 'technical' THEN 1 ELSE 2 END, id "
                "LIMIT ?",
                (licitacion_id, max(1, min(int(limit), 100))),
            )
            return rows_to_dicts(cur)

    def count_chunks(self, documento_id: int) -> int:
        with connect_read() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM documento_chunks WHERE documento_id = ?",
                (documento_id,),
            ).fetchone()
            return int(row[0] if row else 0)

    def count_all(self) -> int:
        """Total de filas en ``documentos`` -- usado por scripts de backfill para
        reportar progreso (antes/después)."""
        with connect_read() as c:
            row = c.execute("SELECT COUNT(*) FROM documentos").fetchone()
            return int(row[0] if row else 0)

    def status_counts(self) -> dict[str, int]:
        """Recuento de ``documentos`` por ``status`` + total de chunks.

        Usado por el reporting del job de embeddings (antes vivía como SQL
        inline en un heredoc de ``pliegos.yml``). Devuelve siempre las claves
        conocidas del ciclo de vida, con 0 cuando no hay filas, para que el
        formato del informe no dependa de los datos.
        """
        counts = {"total": 0, "pending": 0, "downloaded": 0, "extracted": 0, "error": 0}
        with connect_read() as c:
            cur = c.execute("SELECT status, COUNT(*) FROM documentos GROUP BY status")
            for status, n in cur.fetchall():
                counts[str(status)] = int(n)
                counts["total"] += int(n)
            row = c.execute("SELECT COUNT(*) FROM documento_chunks").fetchone()
            counts["chunks"] = int(row[0] if row else 0)
        return counts
