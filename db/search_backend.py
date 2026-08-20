"""Abstracción de búsqueda full-text (ADR-016, ADR-021).

Define el protocolo ``SearchBackend`` y su única implementación:

- ``PgTsBackend``: ``tsvector``/``ts_rank_cd`` de Postgres, con relajación
  AND→OR de la tsquery, fallback ``pg_trgm`` y búsqueda híbrida (RRF sobre
  ``pg_trgm`` + pgvector).

``Fts5Backend`` (SQLite) se retiró en ADR-021 junto con el motor. El protocolo
se conserva: sigue siendo el punto de extensión si algún día entra otro motor
de búsqueda, y es lo que permite testear los call-sites con un doble.

El módulo expone ``get_search_backend()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from observability.logging import get_logger

log = get_logger(__name__)

if TYPE_CHECKING:
    pass

# Constante estándar de Reciprocal Rank Fusion (Cormack et al. 2009) — el
# valor 60 es el usado en la literatura y en la mayoría de motores híbridos
# (Elasticsearch, Weaviate...); no es un hiperparámetro que este proyecto
# tenga motivos para ajustar.
RRF_K = 60

# ── Ranking FTS: los dos knobs que NO son migración ──────────────────────
#
# El etiquetado de lexemas lo fija el esquema: ``search_vector`` (migración
# v50) es ``setweight(titulo,'A') || setweight(descripcion,'B') ||
# setweight(cpv,'C')``. Cambiar esas etiquetas —o materializar otra columna—
# es una migración Alembic. Lo que sí se decide en la propia consulta es
# **cuánto vale** cada etiqueta y **cuánto se normaliza** el score; por eso
# ambos viven aquí y no en el esquema.

# Pesos ``{D, C, B, A}`` del 1er argumento de ``ts_rank_cd``. Son los valores
# por defecto de Postgres, escritos explícitos: el título (A) vale 2.5x la
# descripción (B) y 5x el cpv (C). Explícitos porque son el único peso de
# ranking tuneable sin tocar el esquema, y ``tests/eval/test_eval_rag.py``
# mide el MRR que producen sobre el golden set.
TS_RANK_WEIGHTS = "{0.1, 0.2, 0.4, 1.0}"

# Bitmask de normalización (4º argumento de ``ts_rank_cd``). 0 = ninguna, a
# propósito: todas las opciones de longitud (1, 2, 8, 16) dividen el score por
# el tamaño del documento, y en este corpus eso premia justo al documento
# equivocado — las licitaciones genéricas ("Soporte SAP genérico") son cortas,
# y las relevantes son largas porque además del término distintivo arrastran
# vocabulario de contexto. Cambiar esto sin medir el MRR es apostar en contra.
TS_RANK_NORMALIZATION = 0


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
# Backend PgTs (Postgres — único desde ADR-021)
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
    sustituye a ``escape_fts5``. Si esa query (AND de todos los términos) no
    casa con nada, relaja a OR sobre ``plainto_tsquery`` antes de rendirse;
    solo si ``search_vector`` no existe (BD anterior a v50) cae al ILIKE.

    ``ts_rank_cd`` (cover density) para ranking, con los pesos y la
    normalización de ``TS_RANK_WEIGHTS``/``TS_RANK_NORMALIZATION``.
    """

    _LANG = "spanish"

    # Las dos tsquery de ``_ts_search``, de más a menos precisa. Ambas dejan
    # sus dos ``%s`` (configuración + texto) en el mismo orden.
    _STRICT_TSQUERY = "websearch_to_tsquery(%s, %s)"
    # Se relaja sobre ``plainto_tsquery`` y NO sobre ``websearch_to_tsquery``
    # a propósito: la salida de ``plainto_tsquery`` es siempre una conjunción
    # plana de lexemas, así que sustituir ` & ` por ` | ` no puede cambiar la
    # semántica de nada más. Relajar la de ``websearch_to_tsquery`` sí podría:
    # un `-término` del usuario se volvería «… o NO contiene término», que casa
    # con casi todo el corpus, y una frase entrecomillada (`<->`) perdería su
    # razón de ser.
    _RELAXED_TSQUERY = "replace(plainto_tsquery(%s, %s)::text, ' & ', ' | ')::tsquery"

    def available(self) -> bool:
        """True si la columna ``search_vector`` existe."""
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
        """Búsqueda ``tsvector`` rankeada por ``ts_rank_cd``, en dos pasadas.

        ``websearch_to_tsquery`` combina los términos con AND, así que una
        pregunta en lenguaje natural —"migración a Oracle Cloud **llamada**
        Aurora Boreal"— solo casa si el documento contiene *todas* sus
        palabras de contenido, incluidas las que solo existen en la pregunta
        ("llamada", "denominado", "apodado"). Cuando no casa, la consulta no
        devuelve un mal orden: devuelve **cero filas**, y quien llama se queda
        sin ranking que usar.

        Por eso hay una segunda pasada: la misma búsqueda con los términos
        en OR, ordenada otra vez por ``ts_rank_cd``, que puntúa cuántos
        términos cubre cada documento y con qué peso (título = A en
        ``search_vector``). Es recall recuperado *con* orden, en lugar de
        recall recuperado sin orden.

        El desempate por ``id_externo`` hace el orden total y estable: sin él,
        dos documentos con el mismo rank salen en el orden que quiera el plan
        de ejecución, lo que rompe tanto la paginación por ``OFFSET`` como
        cualquier medición reproducible del ranking.

        La tercera pasada (ILIKE) es para BD anteriores a v50, donde no existe
        ``search_vector`` y las dos primeras fallan con error —no con cero
        filas—; de ahí que ``_ts_search_pass`` distinga ambos casos.
        """
        rows = self._ts_search_pass(conn, query, self._STRICT_TSQUERY, limit=limit, offset=offset)
        if rows is None:
            return self._ilike_search(conn, query, limit=limit, offset=offset)
        if rows:
            return rows

        relaxed = self._ts_search_pass(
            conn, query, self._RELAXED_TSQUERY, limit=limit, offset=offset
        )
        if relaxed is None:
            return self._ilike_search(conn, query, limit=limit, offset=offset)
        return relaxed

    def _ts_search_pass(
        self,
        conn: Any,
        query: str,
        tsquery_sql: str,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[str, float]] | None:
        """Una pasada FTS con la tsquery dada, o ``None`` si no se pudo buscar.

        La distinción importa: ``[]`` significa "el motor buscó y no hay
        coincidencias" (relajar la query puede ayudar), mientras que ``None``
        significa "la consulta ni siquiera se pudo ejecutar" —típicamente una
        BD sin ``search_vector``— y ahí lo único que queda es el ILIKE.
        """
        rank_expr = (
            f"ts_rank_cd('{TS_RANK_WEIGHTS}'::float4[], search_vector, "
            f"{tsquery_sql}, {TS_RANK_NORMALIZATION})"
        )
        sql = (
            f"SELECT id_externo, {rank_expr} AS rank "
            "FROM licitaciones "
            f"WHERE search_vector @@ {tsquery_sql} "
            "ORDER BY rank DESC, id_externo "
            "LIMIT %s OFFSET %s"
        )
        try:
            rows = conn.execute(
                sql, (self._LANG, query, self._LANG, query, limit, offset)
            ).fetchall()
        except Exception:
            # Sin log, una búsqueda degradada es indistinguible de una
            # búsqueda que simplemente no encontró nada.
            log.warning("ts_search_pass_failed", exc_info=True)
            return None
        return [(r[0], float(r[1])) for r in rows]

    def _ilike_search(
        self,
        conn: Any,
        query: str,
        *,
        limit: int,
        offset: int,
    ) -> list[tuple[str, float]]:
        """Último recurso para BD sin ``search_vector`` (antes de v50).

        Sin ranking posible: todas las filas comparten score, así que el orden
        lo fija ``id_externo`` para que al menos sea determinista.
        """
        try:
            pattern = f"%{query}%"
            sql = (
                "SELECT id_externo, 0.5 AS rank "
                "FROM licitaciones "
                "WHERE titulo ILIKE %s OR descripcion ILIKE %s "
                "ORDER BY id_externo "
                "LIMIT %s OFFSET %s"
            )
            rows = conn.execute(sql, (pattern, pattern, limit, offset)).fetchall()
            return [(r[0], float(r[1])) for r in rows]
        except Exception:
            log.warning("ts_search_failed", exc_info=True)
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
            log.warning("hybrid_search_docs_failed", exc_info=True)
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
# Entradas con conexión propia
# ---------------------------------------------------------------------------


def hybrid_search_docs(
    query: str,
    query_embedding: list[float],
    *,
    ccaa: str | None = None,
    tecnologia: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """``PgTsBackend.hybrid_search_docs`` abriendo su propia conexión de lectura.

    El método del backend recibe la conexión porque hay call-sites que ya
    están dentro de una; ``services/licitaciones.py::search_for_ask`` no lo
    está, y abrirla allí era una de las entradas del ratchet TID251. ADR-022:
    la conexión se abre en ``db/``.

    Fail-open igual que el método: los errores de consulta ya los captura y
    loguea ``hybrid_search_docs``, que devuelve lista vacía. Lo que sí puede
    escapar de aquí es un fallo al **abrir** la conexión (Postgres caído); el
    llamador decide si eso degrada a FTS o propaga.
    """
    from db.database import connect_read

    with connect_read() as conn:
        return PgTsBackend().hybrid_search_docs(
            conn,
            query,
            query_embedding,
            ccaa=ccaa,
            tecnologia=tecnologia,
            limit=limit,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_BACKEND: SearchBackend | None = None


def get_search_backend() -> SearchBackend:
    """Devuelve el backend de búsqueda.

    Siempre ``PgTsBackend`` desde ADR-021. Si ``search_vector`` todavía no
    existe (BD anterior a la migración v50), ``search_ids`` cae al fallback
    ``pg_trgm``, así que devolverlo igualmente es correcto.
    """
    return PgTsBackend()
