"""Abstracción de búsqueda full-text (ADR-016, ADR-021).

Implementación única, ``PgTsBackend``: ``tsvector``/``ts_rank_cd`` de Postgres, con relajación
  AND→OR de la tsquery, fallback ``pg_trgm`` y búsqueda híbrida (RRF sobre
  ``pg_trgm`` + pgvector).

``Fts5Backend`` (SQLite) se retiró en ADR-021 junto con el motor, y con él (el
2026-09-28) el protocolo ``SearchBackend``, su factoría y los métodos que solo
usaban los tests. La producción entra por :func:`hybrid_search_docs`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from observability.logging import get_logger

log = get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def fusion_weights(alpha: float | None) -> tuple[float, float]:
    """Pesos ``(fts, vectorial)`` de la fusión RRF para un ``alpha`` dado.

    ``alpha`` es el peso del lado **semántico**: ``0.0`` = solo FTS, ``1.0`` =
    solo similitud vectorial. Es el mismo eje que el deslizador del
    Investigador, que hasta 2026-09 no llegaba al backend.

    ``None`` —el valor por defecto de ``hybrid_search_docs``— devuelve
    ``(1.0, 1.0)``: la fusión sin ponderar de siempre, que es la que sirve el
    RAG. Se conserva bit a bit porque multiplicar un float por ``1.0`` no lo
    altera, así que añadir el peso a la consulta no cambia el ranking de
    ``/ask`` ni por un ULP.

    El escalado por 2 existe para que ``alpha=0.5`` —"tanto peso a una lista como
    a la otra"— produzca exactamente ese mismo ``(1.0, 1.0)`` en lugar de
    ``(0.5, 0.5)``, que ordenaría igual pero con scores de otra magnitud.
    """
    if alpha is None:
        return (1.0, 1.0)
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"alpha debe estar en [0, 1], recibido {alpha}")
    return (2.0 * (1.0 - alpha), 2.0 * alpha)


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
        ccaa: str | Sequence[str] | None = None,
        tecnologia: str | Sequence[str] | None = None,
        fecha_desde: str | None = None,
        fecha_hasta: str | None = None,
        importe_min: float | None = None,
        importe_max: float | None = None,
        solo_abiertas: bool = False,
        limit: int = 20,
        candidate_k: int = 50,
        alpha: float | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieval híbrido: FTS (tsvector) + similitud vectorial (``documento_chunks``),
        fusionados con Reciprocal Rank Fusion en una sola query (un round-trip).

        Devuelve licitaciones ordenadas por ``rrf_score`` desc, cada una con
        una clave ``chunks`` (lista de ``{chunk_id, chunk_index, texto}``,
        posiblemente vacía) con los fragmentos de pliego que la citan —
        fuentes citables para la síntesis del LLM en ``/ask``.

        ``candidate_k`` es el top-k de CADA lista (FTS y vectorial) *antes*
        de fusionar; ``limit`` es el número final de licitaciones devueltas
        tras la fusión. ``alpha`` pondera las dos listas (ver
        ``fusion_weights``): ``None`` es la fusión sin ponderar que consume el
        RAG y que este parámetro no altera. Solo Postgres — requiere
        ``search_vector`` (v50) y ``documento_chunks``/pgvector (v56).
        Fail-open: cualquier error (extensión ausente, tabla vacía) devuelve
        lista vacía, igual que ``_ts_search``.

        Los filtros (``ccaa``, ``tecnologia``, ``fecha_desde``/``fecha_hasta`` y,
        desde el Investigador, ``importe_min``/``importe_max``/``solo_abiertas``;
        ver ``db.repositories.base.ambito_busqueda_sql``) acotan las **dos**
        listas antes de fusionar, así que el ranking de cada una se cuenta ya
        dentro del ámbito y ningún fragmento de fuera llega a ``chunks``.
        """
        w_fts, w_vec = fusion_weights(alpha)
        # Con ``alpha=None`` la consulta es, carácter a carácter, la de siempre:
        # ni una columna ni un parámetro de más. La igualdad numérica de
        # multiplicar por 1.0 ya bastaría, pero mantener el SQL idéntico es lo
        # que hace comprobable que servir el deslizador del Investigador no
        # cambia el plan de ejecución ni el ranking del RAG.
        ponderada = alpha is not None
        w_col = "%s::float8 AS w, " if ponderada else ""
        union_cols = "w, rnk" if ponderada else "rnk"
        sum_expr = "SUM(w / (%s + rnk))" if ponderada else "SUM(1.0 / (%s + rnk))"
        # Solo actúa en los extremos del deslizador: con ``alpha=0`` (o ``1``)
        # una de las dos listas pesa cero y sus documentos exclusivos entrarían
        # con score 0, ocupando plazas del ``LIMIT`` por detrás de todo. Sin
        # ponderar, todos los sumandos son positivos y el filtro sobra.
        filtro_positivos = "WHERE f.rrf_score > 0\n            " if ponderada else ""

        # Import local, como `connect_read`: importar este módulo no carga el
        # paquete de repositories.
        from db.repositories.base import ambito_busqueda_sql

        # Las mismas cláusulas que el FTS y el LIKE a los que cae
        # `search_for_ask`: la tecnología se busca en el CSV de la fila («ERP,SAP»
        # también es SAP) y un CSV de varios códigos se trocea.
        ambito, ambito_params = ambito_busqueda_sql(
            "l",
            ccaa=ccaa,
            tecnologia=tecnologia,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            importe_min=importe_min,
            importe_max=importe_max,
            solo_abiertas=solo_abiertas,
        )
        fts_where = " AND ".join(
            ["l.search_vector @@ websearch_to_tsquery('spanish', %s)", *ambito]
        )
        # El mismo ámbito en la lista vectorial. Sin él, `vec_ranked` traía los
        # fragmentos más cercanos de cualquier licitación, y la fusión los
        # devolvía con sus `chunks`: una respuesta filtrada por SAP citaba el
        # pliego de otra tecnología. Sin filtros no hay JOIN y la consulta es la
        # de siempre. Con ellos, si el plan usa el índice HNSW, el filtro se
        # aplica sobre los `hnsw.ef_search` vecinos que devuelve: un ámbito muy
        # estrecho puede dejar menos de `candidate_k` fragmentos, nunca uno de
        # fuera.
        vec_ambito = (
            "\n                JOIN licitaciones l ON l.id_externo = d.licitacion_id"
            f"\n                WHERE {' AND '.join(ambito)}"
            if ambito
            else ""
        )
        qvec = _to_pg_vector_literal(query_embedding)

        sql = f"""
            WITH fts_ranked AS (
                SELECT l.id_externo,
                       {w_col}ROW_NUMBER() OVER (
                           ORDER BY ts_rank_cd(l.search_vector, websearch_to_tsquery('spanish', %s)) DESC
                       ) AS rnk
                FROM licitaciones l
                WHERE {fts_where}
                LIMIT %s
            ),
            vec_ranked AS (
                SELECT d.licitacion_id, dc.id AS chunk_id, dc.chunk_index,
                       dc.texto AS chunk_texto,
                       {w_col}ROW_NUMBER() OVER (ORDER BY dc.embedding <=> %s::vector) AS rnk
                FROM documento_chunks dc
                JOIN documentos d ON d.id = dc.documento_id{vec_ambito}
                ORDER BY dc.embedding <=> %s::vector
                LIMIT %s
            ),
            fused AS (
                SELECT id_externo, {sum_expr} AS rrf_score
                FROM (
                    SELECT id_externo, {union_cols} FROM fts_ranked
                    UNION ALL
                    SELECT licitacion_id AS id_externo, {union_cols} FROM vec_ranked
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
            {filtro_positivos}ORDER BY f.rrf_score DESC
            LIMIT %s
        """
        exec_params = [
            *([w_fts] if ponderada else []),
            query,
            query,
            *ambito_params,
            candidate_k,
            *([w_vec] if ponderada else []),
            qvec,
            *ambito_params,
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


def document_embeddings_available() -> bool:
    """True si ``documento_chunks`` tiene al menos un embedding que fusionar.

    Es lo que separa una fusión RRF real de una fusión con una sola lista:
    sin chunks embebidos, ``hybrid_search_docs`` devuelve exactamente el orden
    del FTS y llamarla «híbrida» sería mentir. Los llamadores derivan de aquí
    la etiqueta de la fuente que sirven, en vez de declararla por
    configuración.

    Fail-closed: si la tabla no existe (BD anterior a v56), pgvector no está o
    la conexión falla, la respuesta es «no hay embeddings» — la degradación a
    FTS es la correcta en los tres casos.
    """
    from db.database import connect_read

    try:
        with connect_read() as conn:
            row = conn.execute(
                "SELECT 1 FROM documento_chunks WHERE embedding IS NOT NULL LIMIT 1"
            ).fetchone()
            return row is not None
    except Exception:
        log.debug("document_embeddings_available_failed", exc_info=True)
        return False


def hybrid_search_docs(
    query: str,
    query_embedding: list[float],
    *,
    ccaa: str | Sequence[str] | None = None,
    tecnologia: str | Sequence[str] | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    importe_min: float | None = None,
    importe_max: float | None = None,
    solo_abiertas: bool = False,
    limit: int = 20,
    candidate_k: int = 50,
    alpha: float | None = None,
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
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            importe_min=importe_min,
            importe_max=importe_max,
            solo_abiertas=solo_abiertas,
            limit=limit,
            candidate_k=candidate_k,
            alpha=alpha,
        )
