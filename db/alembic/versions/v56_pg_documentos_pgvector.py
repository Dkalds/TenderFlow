"""Migracion v56 -- pgvector + tablas documentos/documento_chunks (Postgres).

Esta migracion es DIALECT-GUARDED: solo hace algo en Postgres, siguiendo el
patron establecido desde v50 (todas las migraciones post-cutover son
Postgres-only; el equivalente SQLite vive en ``db/schema.py::SCHEMA``, que es
lo que ``init_db()``/el fixture ``tmp_db`` usan realmente para poblar una BD
SQLite de desarrollo/tests -- ``alembic upgrade head`` nunca se ejecuta contra
un SQLite real en ese camino).

Fase A1 del plan Pliegos+RAG (2026-07-13): fundacion de persistencia para
ingerir el *contenido* de las licitaciones (pliegos), no solo metadatos.

Decision de producto (v1): solo se persiste texto extraido + metadatos + URL
de origen. El PDF se descarga transitoriamente para extraer el texto y se
descarta -- no hay blob storage. ``storage_key`` queda reservado (NULL) para
anadir blobs en el futuro sin otra migracion.

Que crea:
  1. Extension ``vector`` (pgvector) -- ``CREATE EXTENSION IF NOT EXISTS``.
  2. ``documentos``: metadatos de cada adjunto de una licitacion (legal/
     technical/additional, via ``scraper/codice_parser.py``), URL de origen,
     y el texto extraido (NULL hasta que el fetcher lo procese). Estado
     ``pending|downloaded|extracted|error`` trackea el pipeline batch (F8).
     ``UNIQUE(licitacion_id, uri)`` -- idempotente frente a re-ingesta.
  3. ``documento_chunks``: fragmentos del texto extraido con su embedding
     (384-dim, ``paraphrase-multilingual-MiniLM-L12-v2`` -- mismo modelo que
     ``services/embeddings.py::encode_texts()``) para retrieval semantico, mas
     una columna generada ``search_vector`` (FTS lexico) para el retrieval
     hibrido de F9 (fusion RRF). Indice HNSW ``vector_cosine_ops`` sobre el
     embedding (decision de arquitectura: HNSW en vez de IVFFlat -- no
     requiere ANALYZE con datos existentes para un buen recall inicial).
     ``UNIQUE(documento_id, chunk_index)`` -- reinsercion idempotente por sha256
     (delete+reinsert en el job de embeddings, no upsert por chunk).

Revision ID: v56_pg_documentos_pgvector
Revises: v55_pg_v27_v49_tables_backfill
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op

revision: str = "v56_pg_documentos_pgvector"
down_revision: str | None = "v55_pg_v27_v49_tables_backfill"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _is_postgres() -> bool:
    bind = op.get_bind()
    return bind.dialect.name == "postgresql"


_CREATE_EXTENSION_VECTOR = "CREATE EXTENSION IF NOT EXISTS vector"

_CREATE_DOCUMENTOS = """
CREATE TABLE IF NOT EXISTS documentos (
    id            SERIAL PRIMARY KEY,
    licitacion_id TEXT NOT NULL REFERENCES licitaciones(id_externo) ON DELETE CASCADE,
    tipo          TEXT NOT NULL CHECK (tipo IN ('legal', 'technical', 'additional')),
    uri           TEXT NOT NULL,
    filename      TEXT,
    content_type  TEXT,
    size_bytes    INTEGER,
    sha256        TEXT,
    texto         TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'downloaded', 'extracted', 'error')),
    error_detail  TEXT,
    storage_key   TEXT,
    fetched_at    TEXT,
    created_at    TEXT NOT NULL DEFAULT NOW(),
    updated_at    TEXT NOT NULL DEFAULT NOW(),
    UNIQUE (licitacion_id, uri)
)
"""

_CREATE_DOCUMENTO_CHUNKS = """
CREATE TABLE IF NOT EXISTS documento_chunks (
    id            SERIAL PRIMARY KEY,
    documento_id  INTEGER NOT NULL REFERENCES documentos(id) ON DELETE CASCADE,
    chunk_index   INTEGER NOT NULL,
    texto         TEXT NOT NULL,
    embedding     vector(384),
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('spanish', coalesce(texto, ''))) STORED,
    UNIQUE (documento_id, chunk_index)
)
"""

_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_documentos_licitacion ON documentos(licitacion_id)",
    "CREATE INDEX IF NOT EXISTS idx_documentos_status ON documentos(status)",
    "CREATE INDEX IF NOT EXISTS idx_documento_chunks_documento ON documento_chunks(documento_id)",
    "CREATE INDEX IF NOT EXISTS idx_documento_chunks_search_vector "
    "ON documento_chunks USING GIN (search_vector)",
    # HNSW (decision de arquitectura, plan Pliegos+RAG): construye bien sobre
    # tabla vacia, a diferencia de IVFFlat que recomienda datos existentes
    # para clusterizar centroides. vector_cosine_ops porque encode_texts()
    # normaliza (paraphrase-multilingual-MiniLM-L12-v2 + cosine es el espacio
    # de similitud estandar para ese modelo).
    "CREATE INDEX IF NOT EXISTS idx_documento_chunks_embedding_hnsw "
    "ON documento_chunks USING hnsw (embedding vector_cosine_ops)",
)


def upgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite -- ver db/schema.py (documentos/documento_chunks)

    op.execute(_CREATE_EXTENSION_VECTOR)
    op.execute(_CREATE_DOCUMENTOS)
    op.execute(_CREATE_DOCUMENTO_CHUNKS)
    for stmt in _INDEXES:
        op.execute(stmt)


def downgrade() -> None:
    if not _is_postgres():
        return  # no-op en SQLite

    op.execute("DROP INDEX IF EXISTS idx_documento_chunks_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS idx_documento_chunks_search_vector")
    op.execute("DROP INDEX IF EXISTS idx_documento_chunks_documento")
    op.execute("DROP TABLE IF EXISTS documento_chunks")
    op.execute("DROP INDEX IF EXISTS idx_documentos_status")
    op.execute("DROP INDEX IF EXISTS idx_documentos_licitacion")
    op.execute("DROP TABLE IF EXISTS documentos")
    # No dropeamos la extension vector: puede estar en uso por otros objetos.
