"""Abstracción de búsqueda full-text multi-backend (ADR-016, F3a).

Define el protocolo ``SearchBackend`` y dos implementaciones:

- ``Fts5Backend``: FTS5 de SQLite (comportamiento actual, código verbatim).
- ``PgTsBackend``: ``tsvector``/``tsquery`` de Postgres con pg_trgm fallback.

El módulo expone ``get_search_backend()`` que detecta el backend activo y
devuelve la instancia correcta. Los call-sites en:
  - ``db/repositories/licitaciones.py``
  - ``db/upsert.py`` (``fts_available()``)
  - ``services/investigador/search_engine.py``
  - ``api/routes/ask.py`` y ``api/routes/search.py``
…se recablearán a este módulo en F3b.

Durante F3a el backend activo es siempre FTS5 (SQLite); PgTsBackend se
instancia pero no se expone en producción hasta que DATABASE_URL apunte a
Postgres y la migración v50 haya creado search_vector + índice GIN.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass

# Constante estándar de Reciprocal Rank Fusion (Cormack et al. 2009) — el
# valor 60 es el usado en la literatura y en la mayoría de motores híbridos
# (Elasticsearch, Weaviate...); no es un hiperparámetro que este proyecto
# tenga motivos para ajustar.
RRF_K = 60


def rrf_score(rank: int, k: int = RRF_K) -> float:
    """Score de Reciprocal Rank Fusion para una posición ``rank`` (1-indexado).

    ``Σ 1/(k+rank)`` sobre todas las listas rankeadas en las que aparece un
    documento — un documento que rankea alto en FTS *y* en similitud
    vectorial acumula la suma de ambos scores, superando a uno que solo
    aparece en una lista. Función pura: la fusión real (agregación por
    documento) ocurre en SQL (``PgTsBackend.hybrid_search_docs``), pero la
    fórmula en sí es la misma — se expone aquí para poder testearla
    unitariamente sin una BD.
    """
    if rank < 1:
        raise ValueError(f"rank debe ser >= 1 (1-indexado), recibido {rank}")
    return 1.0 / (k + rank)


# ---------------------------------------------------------------------------
# Protocolo
# ---------------------------------------------------------------------------


@runtime_checkable
class SearchBackend(Protocol):
    """Contrato mínimo de un backend de búsqueda full-text."""

    def available(self) -> bool:
        """True si el backend está operativo en la BD actual."""
        ...

    def search_ids(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[str]:
        """Devuelve lista de id_externo ordenados por relevancia."""
        ...

    def search_docs(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Devuelve dicts con id_externo + campos de contexto (snippet)."""
        ...

    def ranked_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        """Devuelve (id_externo, score) ordenados por relevancia."""
        ...


# ---------------------------------------------------------------------------
# Backend FTS5 (SQLite — actual)
# ---------------------------------------------------------------------------


class Fts5Backend:
    """Implementación FTS5 para SQLite.

    Replica el comportamiento actual de ``db/upsert.py:search_fts`` y de
    ``services/investigador/search_engine.py:fts5_search`` sin cambiar la
    semántica. Los call-sites que ya usan esas funciones no cambian para el
    cutover; este backend es el envoltorio formal para la abstracción.
    """

    def available(self) -> bool:
        """True si la tabla FTS5 ``licitaciones_fts`` existe."""
        try:
            from db.database import fts_available

            return fts_available()
        except Exception:
            return False

    def search_ids(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[str]:
        from db.database import search_fts

        rows, _ = search_fts(query, limit=limit, offset=offset)
        return [r["id_externo"] for r in rows]

    def search_docs(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        from db.database import search_fts

        rows, _ = search_fts(query, limit=limit, offset=offset)
        return list(rows)

    def ranked_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        """FTS5 bm25 rank (valores negativos = más relevante)."""
        try:
            from db.connection import _translate_qmarks

            sql = _translate_qmarks(
                "SELECT l.id_externo, bm25(licitaciones_fts) AS score "
                "FROM licitaciones_fts "
                "JOIN licitaciones l ON l.id_externo = licitaciones_fts.id_externo "
                "WHERE licitaciones_fts MATCH ? "
                "ORDER BY score "
                "LIMIT ?"
            )
            rows = conn.execute(sql, (query, limit)).fetchall()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Backend PgTs (Postgres — destino F3)
# ---------------------------------------------------------------------------


def _to_pg_vector_literal(vec: list[float]) -> str:
    """Formato de texto que pgvector castea con ``::vector`` (``[0.1,0.2,...]``).

    Duplicado deliberadamente de ``db/repositories/documentos.py`` (misma
    función, dos líneas): evita que ``db/search_backend.py`` (capa de
    abstracción de búsqueda) dependa de un repository concreto.
    """
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


class PgTsBackend:
    """Implementación tsvector/tsquery para Postgres (ADR-016).

    Usa ``websearch_to_tsquery('spanish', query)`` — inmune a inyección SQL,
    sustituye a ``escape_fts5``. Fallback a pg_trgm LIKE si la columna
    ``search_vector`` no existe aún (antes de v50).

    ``ts_rank_cd`` (cover density) para ranking.
    """

    _LANG = "spanish"

    def available(self) -> bool:
        """True si Postgres está activo y la columna search_vector existe."""
        from db.connection import is_postgres_backend

        if not is_postgres_backend():
            return False
        try:
            from db.database import connect_read

            with connect_read() as conn:
                cur = conn.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='licitaciones' AND column_name='search_vector' LIMIT 1"
                )
                return cur.fetchone() is not None
        except Exception:
            return False

    def search_ids(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[str]:
        rows = self._ts_search(conn, query, limit=limit, offset=offset)
        return [r[0] for r in rows]

    def search_docs(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = self._ts_search(conn, query, limit=limit, offset=offset)
        return [{"id_externo": r[0], "score": r[1]} for r in rows]

    def ranked_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        return self._ts_search(conn, query, limit=limit)

    def _ts_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[tuple[str, float]]:
        """Búsqueda con tsvector + ts_rank_cd; fallback a pg_trgm si search_vector no existe."""
        # Intento 1: tsvector GIN (óptimo)
        try:
            sql = (
                "SELECT id_externo, ts_rank_cd(search_vector, websearch_to_tsquery(%s, %s)) AS rank "
                "FROM licitaciones "
                "WHERE search_vector @@ websearch_to_tsquery(%s, %s) "
                "ORDER BY rank DESC "
                "LIMIT %s OFFSET %s"
            )
            rows = conn.execute(
                sql, (self._LANG, query, self._LANG, query, limit, offset)
            ).fetchall()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:
            pass

        # Fallback: pg_trgm ILIKE (antes de que exista search_vector)
        try:
            pattern = f"%{query}%"
            sql = (
                "SELECT id_externo, 0.5 AS rank "
                "FROM licitaciones "
                "WHERE titulo ILIKE %s OR descripcion ILIKE %s "
                "LIMIT %s OFFSET %s"
            )
            rows = conn.execute(sql, (pattern, pattern, limit, offset)).fetchall()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:
            return []

    # ── Retrieval híbrido (plan Pliegos+RAG, F9 — cierra la deuda F3b) ──────

    def hybrid_search_docs(
        self,
        conn: Any,
        query: str,
        query_embedding: list[float],
        *,
        ccaa: str | None = None,
        tecnologia: str | None = None,
        limit: int = 20,
        candidate_k: int = 50,
    ) -> list[dict[str, Any]]:
        """Retrieval híbrido: FTS (tsvector) + similitud vectorial (``documento_chunks``),
        fusionados con Reciprocal Rank Fusion en una sola query (un round-trip).

        Devuelve licitaciones ordenadas por ``rrf_score`` desc, cada una con
        una clave ``chunks`` (lista de ``{chunk_id, chunk_index, texto}``,
        posiblemente vacía) con los fragmentos de pliego que la citan —
        fuentes citables para la síntesis del LLM en ``/ask``.

        ``candidate_k`` es el top-k de CADA lista (FTS y vectorial) *antes*
        de fusionar; ``limit`` es el número final de licitaciones devueltas
        tras la fusión. Solo Postgres — requiere ``search_vector`` (v50) y
        ``documento_chunks``/pgvector (v56). Fail-open: cualquier error
        (extensión ausente, tabla vacía) devuelve lista vacía, igual que
        ``_ts_search``.
        """
        conditions = ["l.search_vector @@ websearch_to_tsquery('spanish', %s)"]
        fts_params: list[Any] = [query]
        if ccaa:
            conditions.append("l.ccaa = %s")
            fts_params.append(ccaa)
        if tecnologia:
            conditions.append("l.tecnologia = %s")
            fts_params.append(tecnologia)
        fts_where = " AND ".join(conditions)
        qvec = _to_pg_vector_literal(query_embedding)

        sql = f"""
            WITH fts_ranked AS (
                SELECT l.id_externo,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank_cd(l.search_vector, websearch_to_tsquery('spanish', %s)) DESC
                       ) AS rnk
                FROM licitaciones l
                WHERE {fts_where}
                LIMIT %s
            ),
            vec_ranked AS (
                SELECT d.licitacion_id, dc.id AS chunk_id, dc.chunk_index,
                       dc.texto AS chunk_texto,
                       ROW_NUMBER() OVER (ORDER BY dc.embedding <=> %s::vector) AS rnk
                FROM documento_chunks dc
                JOIN documentos d ON d.id = dc.documento_id
                ORDER BY dc.embedding <=> %s::vector
                LIMIT %s
            ),
            fused AS (
                SELECT id_externo, SUM(1.0 / (%s + rnk)) AS rrf_score
                FROM (
                    SELECT id_externo, rnk FROM fts_ranked
                    UNION ALL
                    SELECT licitacion_id AS id_externo, rnk FROM vec_ranked
                ) u
                GROUP BY id_externo
            ),
            chunks_per_lic AS (
                SELECT licitacion_id,
                       json_agg(
                           json_build_object(
                               'chunk_id', chunk_id, 'chunk_index', chunk_index, 'texto', chunk_texto
                           ) ORDER BY rnk
                       ) AS chunks
                FROM vec_ranked
                GROUP BY licitacion_id
            )
            SELECT l.id_externo, l.titulo, l.organo_contratacion, l.importe,
                   l.descripcion, l.url, l.fecha_publicacion, l.ccaa, l.estado,
                   l.tecnologia, f.rrf_score, c.chunks
            FROM fused f
            JOIN licitaciones l ON l.id_externo = f.id_externo
            LEFT JOIN chunks_per_lic c ON c.licitacion_id = f.id_externo
            ORDER BY f.rrf_score DESC
            LIMIT %s
        """
        exec_params = [
            query,
            *fts_params,
            candidate_k,
            qvec,
            qvec,
            candidate_k,
            RRF_K,
            limit,
        ]

        try:
            rows = conn.execute(sql, exec_params).fetchall()
        except Exception:
            return []

        cols = (
            "id_externo",
            "titulo",
            "organo_contratacion",
            "importe",
            "descripcion",
            "url",
            "fecha_publicacion",
            "ccaa",
            "estado",
            "tecnologia",
            "rrf_score",
            "chunks",
        )
        results: list[dict[str, Any]] = []
        for row in rows:
            d = dict(zip(cols, row, strict=False))
            chunks = d.get("chunks")
            if isinstance(chunks, str):
                import json

                try:
                    chunks = json.loads(chunks)
                except (TypeError, ValueError):
                    chunks = None
            d["chunks"] = chunks or []
            results.append(d)
        return results


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_BACKEND: SearchBackend | None = None


def get_search_backend() -> SearchBackend:
    """Devuelve el backend de búsqueda activo.

    - Postgres con search_vector → ``PgTsBackend``
    - SQLite con FTS5 → ``Fts5Backend``
    - Fallback → ``Fts5Backend`` (puede devolver listas vacías si FTS no está disponible)
    """
    from db.connection import is_postgres_backend

    if is_postgres_backend():
        pg = PgTsBackend()
        if pg.available():
            return pg
        # Postgres activo pero sin search_vector aún (antes de v50)
        return pg  # pg.search_ids usará el fallback pg_trgm

    return Fts5Backend()
