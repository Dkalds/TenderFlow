"""Tests del retrieval híbrido (plan Pliegos+RAG, F9 — cierra la deuda F3b).

``PgTsBackend.hybrid_search_docs`` requiere Postgres+pgvector real para un
test de integración genuino (no disponible en este entorno); aquí se
verifica la fórmula RRF de forma unitaria (sin BD) y la construcción de la
query con una conexión falsa que captura SQL/params — mismo patrón que los
tests de migraciones dialect-guarded (``op.execute`` mockeado).
"""

from __future__ import annotations

import json

import pytest

from db.search_backend import RRF_K, PgTsBackend, _to_pg_vector_literal, rrf_score
from db.sql_fragments import tecnologia_en_csv_sql

# ── RRF: fórmula pura ────────────────────────────────────────────────────


class TestRrfScore:
    def test_matches_formula_for_known_ranks(self):
        assert rrf_score(1) == pytest.approx(1.0 / 61)
        assert rrf_score(2) == pytest.approx(1.0 / 62)
        assert rrf_score(10) == pytest.approx(1.0 / 70)

    def test_uses_default_k_of_60(self):
        assert RRF_K == 60
        assert rrf_score(1) == pytest.approx(1.0 / (60 + 1))

    def test_custom_k(self):
        assert rrf_score(1, k=10) == pytest.approx(1.0 / 11)

    def test_monotonically_decreasing_with_rank(self):
        scores = [rrf_score(r) for r in range(1, 20)]
        assert all(scores[i] > scores[i + 1] for i in range(len(scores) - 1))

    def test_rank_below_one_raises(self):
        with pytest.raises(ValueError, match="rank"):
            rrf_score(0)
        with pytest.raises(ValueError, match="rank"):
            rrf_score(-1)

    def test_document_in_both_lists_scores_higher_than_single_list(self):
        """El caso de uso central de RRF: rankear alto en FTS *y* vectorial
        debe superar a rankear alto en una sola lista."""
        only_fts_rank1 = rrf_score(1)
        both_lists_rank5_each = rrf_score(5) + rrf_score(5)
        assert both_lists_rank5_each > only_fts_rank1


# ── _to_pg_vector_literal ────────────────────────────────────────────────


class TestToPgVectorLiteral:
    def test_formats_as_bracketed_csv(self):
        assert _to_pg_vector_literal([0.1, 0.2, 0.3]) == "[0.1,0.2,0.3]"

    def test_empty_vector(self):
        assert _to_pg_vector_literal([]) == "[]"

    def test_coerces_to_float(self):
        assert _to_pg_vector_literal([1, 2]) == "[1.0,2.0]"


# ── hybrid_search_docs: construcción de query (conexión falsa) ──────────


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Captura la última SQL/params ejecutados; devuelve filas canned."""

    def __init__(self, rows: list[tuple] | None = None, raises: Exception | None = None) -> None:
        self.rows = rows or []
        self.raises = raises
        self.last_sql: str | None = None
        self.last_params: list | None = None

    def execute(self, sql, params):
        self.last_sql = sql
        self.last_params = params
        if self.raises:
            raise self.raises
        return _FakeCursor(self.rows)


_COLS = (
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


def _row(id_externo: str, rrf: float, chunks) -> tuple:
    return (
        id_externo,
        f"Título {id_externo}",
        "Órgano",
        1000.0,
        "desc",
        "http://x",
        "2026-01-01",
        "Madrid",
        "PUB",
        "SAP",
        rrf,
        chunks,
    )


class TestHybridSearchDocsQueryConstruction:
    def test_sql_contains_rrf_formula_and_ctes(self):
        conn = _FakeConn(rows=[])
        PgTsBackend().hybrid_search_docs(conn, "sap basis", [0.1, 0.2], limit=5)

        assert "1.0 / (%s + rnk)" in conn.last_sql
        assert "fts_ranked" in conn.last_sql
        assert "vec_ranked" in conn.last_sql
        assert "UNION ALL" in conn.last_sql
        assert "<=> %s::vector" in conn.last_sql

    def test_param_order_without_filters(self):
        conn = _FakeConn(rows=[])
        query = "sap basis"
        embedding = [0.1, 0.2, 0.3]
        PgTsBackend().hybrid_search_docs(conn, query, embedding, limit=7, candidate_k=30)

        qvec = _to_pg_vector_literal(embedding)
        assert conn.last_params == [
            query,  # ts_rank_cd ORDER BY
            query,  # WHERE @@ match
            30,  # fts_ranked LIMIT (candidate_k)
            qvec,  # vec_ranked ROW_NUMBER ORDER BY
            qvec,  # vec_ranked outer ORDER BY
            30,  # vec_ranked LIMIT (candidate_k)
            RRF_K,  # fused SUM(1.0/(k+rnk))
            7,  # outer LIMIT
        ]

    def test_param_order_with_ccaa_and_tecnologia_filters(self):
        conn = _FakeConn(rows=[])
        PgTsBackend().hybrid_search_docs(
            conn, "q", [0.1], ccaa="Madrid", tecnologia="SAP", limit=5, candidate_k=20
        )

        assert conn.last_params[:4] == ["q", "q", "Madrid", "SAP"]
        assert "l.ccaa = %s" in conn.last_sql
        # El CSV de la fila, no igualdad: «ERP,SAP» también es SAP.
        assert tecnologia_en_csv_sql("l.tecnologia", n=1) in conn.last_sql
        assert "l.tecnologia = " not in conn.last_sql

    def test_tecnologia_csv_is_split_like_the_fts_fallback(self):
        """``/ask`` pasa el mismo ``tecnologia`` al híbrido y a ``search_fts_docs``.

        El FTS al que cae ``search_for_ask`` trocea el CSV con ``csv_values``;
        si el híbrido no lo hiciera, ``"SAP, ORACLE"`` sería un único código que
        no casa con ninguna fila. Un parámetro por código, en el sitio del
        filtro.
        """
        conn = _FakeConn(rows=[])
        PgTsBackend().hybrid_search_docs(conn, "q", [0.1], tecnologia="SAP, ORACLE")

        assert conn.last_params[:4] == ["q", "q", "SAP", "ORACLE"]
        assert tecnologia_en_csv_sql("l.tecnologia", n=2) in conn.last_sql
        assert conn.last_sql.count("%s") == len(conn.last_params)

    def test_returns_docs_with_parsed_dict_chunks(self):
        chunks = [{"chunk_id": 1, "chunk_index": 0, "texto": "fragmento"}]
        conn = _FakeConn(rows=[_row("EXP-1", 0.032, chunks)])

        docs = PgTsBackend().hybrid_search_docs(conn, "q", [0.1])

        assert len(docs) == 1
        assert docs[0]["id_externo"] == "EXP-1"
        assert docs[0]["chunks"] == chunks

    def test_parses_chunks_returned_as_json_string(self):
        """Algunos drivers devuelven json/jsonb como str en vez de dict/list ya parseado."""
        chunks_json = json.dumps([{"chunk_id": 2, "chunk_index": 1, "texto": "otro"}])
        conn = _FakeConn(rows=[_row("EXP-2", 0.02, chunks_json)])

        docs = PgTsBackend().hybrid_search_docs(conn, "q", [0.1])

        assert docs[0]["chunks"] == [{"chunk_id": 2, "chunk_index": 1, "texto": "otro"}]

    def test_null_chunks_becomes_empty_list(self):
        """LEFT JOIN sin match vectorial (solo FTS) -> chunks NULL en SQL."""
        conn = _FakeConn(rows=[_row("EXP-3", 0.016, None)])

        docs = PgTsBackend().hybrid_search_docs(conn, "q", [0.1])

        assert docs[0]["chunks"] == []

    def test_query_exception_returns_empty_list(self):
        """Fail-open: extensión/tabla ausente no debe propagar la excepción."""
        conn = _FakeConn(raises=RuntimeError("relation documento_chunks does not exist"))

        docs = PgTsBackend().hybrid_search_docs(conn, "q", [0.1])

        assert docs == []

    def test_results_ordered_by_rrf_score_as_returned_by_sql(self):
        """El orden lo da la SQL (ORDER BY rrf_score DESC); el wrapper Python
        no reordena -- solo verificamos que preserva el orden de las filas."""
        conn = _FakeConn(rows=[_row("EXP-A", 0.05, None), _row("EXP-B", 0.03, None)])
        docs = PgTsBackend().hybrid_search_docs(conn, "q", [0.1])
        assert [d["id_externo"] for d in docs] == ["EXP-A", "EXP-B"]


# ── hybrid_search_docs: los filtros acotan las DOS listas de la fusión ──


def _cte(sql: str, nombre: str) -> str:
    """Cuerpo del CTE ``nombre``, hasta su paréntesis de cierre."""
    inicio = sql.index(f"{nombre} AS (") + len(f"{nombre} AS (")
    nivel = 1
    for i in range(inicio, len(sql)):
        if sql[i] == "(":
            nivel += 1
        elif sql[i] == ")":
            nivel -= 1
            if nivel == 0:
                return sql[inicio:i]
    raise AssertionError(f"el CTE {nombre} no se cierra")


#: Lo que manda el Investigador con los filtros globales activos.
_FILTROS = {
    "ccaa": ["Galicia", "Madrid"],
    "tecnologia": ["SAP"],
    "fecha_desde": "2026-01-01",
    "fecha_hasta": "2026-06-30",
}


class TestFiltrosEnLasDosListas:
    """Los filtros iban solo en ``fts_ranked``.

    ``vec_ranked`` traía los fragmentos más cercanos de **cualquier**
    licitación, y la fusión los devolvía con sus ``chunks``: en cuanto hubiera
    pliegos embebidos, una respuesta de ``/ask`` filtrada por SAP podía citar
    pliegos de otra tecnología o de otra CCAA.
    """

    def test_el_lado_vectorial_aplica_los_mismos_filtros(self):
        from db.repositories.base import ambito_busqueda_sql

        conn = _FakeConn(rows=[])
        PgTsBackend().hybrid_search_docs(conn, "q", [0.1], **_FILTROS)

        clausulas, _ = ambito_busqueda_sql("l", **_FILTROS)
        fts = _cte(conn.last_sql, "fts_ranked")
        vec = _cte(conn.last_sql, "vec_ranked")
        assert "JOIN licitaciones l ON l.id_externo = d.licitacion_id" in vec
        for clausula in clausulas:
            assert clausula in fts, clausula
            assert clausula in vec, clausula

    def test_sin_filtros_el_lado_vectorial_no_toca_licitaciones(self):
        """Sin filtros la consulta es la de siempre: ni un JOIN de más."""
        conn = _FakeConn(rows=[])
        PgTsBackend().hybrid_search_docs(conn, "q", [0.1])

        assert "licitaciones" not in _cte(conn.last_sql, "vec_ranked")

    def test_orden_de_parametros_con_filtros(self):
        conn = _FakeConn(rows=[])
        embedding = [0.1, 0.2]
        PgTsBackend().hybrid_search_docs(
            conn, "q", embedding, ccaa=["Madrid"], tecnologia=["SAP"], limit=5, candidate_k=20
        )

        qvec = _to_pg_vector_literal(embedding)
        assert conn.last_params == [
            "q",  # ts_rank_cd ORDER BY
            "q",  # WHERE @@ match
            "Madrid",  # fts_ranked: l.ccaa
            "SAP",  # fts_ranked: l.tecnologia
            20,  # fts_ranked LIMIT
            qvec,  # vec_ranked ROW_NUMBER ORDER BY
            "Madrid",  # vec_ranked: l.ccaa
            "SAP",  # vec_ranked: l.tecnologia
            qvec,  # vec_ranked ORDER BY
            20,  # vec_ranked LIMIT
            RRF_K,
            5,  # LIMIT final
        ]
        assert conn.last_sql.count("%s") == len(conn.last_params)

    def test_orden_de_parametros_con_filtros_y_alpha(self):
        from db.search_backend import fusion_weights

        conn = _FakeConn(rows=[])
        embedding = [0.1, 0.2]
        PgTsBackend().hybrid_search_docs(
            conn, "q", embedding, tecnologia=["SAP"], limit=5, candidate_k=20, alpha=0.7
        )

        w_fts, w_vec = fusion_weights(0.7)
        qvec = _to_pg_vector_literal(embedding)
        assert conn.last_params == [
            w_fts,
            "q",
            "q",
            "SAP",
            20,
            w_vec,
            qvec,
            "SAP",
            qvec,
            20,
            RRF_K,
            5,
        ]
        assert conn.last_sql.count("%s") == len(conn.last_params)

    def test_el_csv_y_la_lista_dan_la_misma_consulta(self):
        """``/ask`` manda listas; otros llamantes, el CSV de la barra de ámbito."""
        csv, lista = _FakeConn(rows=[]), _FakeConn(rows=[])
        PgTsBackend().hybrid_search_docs(csv, "q", [0.1], ccaa="Madrid", tecnologia="SAP, ORACLE")
        PgTsBackend().hybrid_search_docs(
            lista, "q", [0.1], ccaa=["Madrid"], tecnologia=["SAP", "ORACLE"]
        )

        assert csv.last_sql == lista.last_sql
        assert csv.last_params == lista.last_params
