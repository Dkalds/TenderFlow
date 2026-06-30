"""Tests for services/investigador/search_engine.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.investigador.search_engine import (
    escape_fts5,
    faiss_search,
    fetch_docs,
    fts5_search,
    hybrid_rerank,
    like_search,
    rag_query,
)

# Module-level _repo for patching (delegates to LicitacionRepository)
_REPO_PATH = "services.investigador.search_engine._repo"

# ---------------------------------------------------------------------------
# escape_fts5 — pure function
# ---------------------------------------------------------------------------


def test_escape_fts5_simple_query() -> None:
    result = escape_fts5("contrato obra pública")
    # Tokens discriminantes se conservan (entre comillas) y se unen con OR.
    assert '"contrato"' in result
    assert '"obra"' in result
    assert " OR " in result


def test_escape_fts5_uses_or_semantics() -> None:
    # Regresión: FTS5 trata el espacio como AND implícito, lo que hacía que
    # preguntas en lenguaje natural no matchearan ningún documento. Los tokens
    # deben unirse con OR explícito.
    result = escape_fts5("consultoría SAP Madrid")
    assert " OR " in result
    # AND implícito (tokens separados solo por espacio sin OR) no debe ocurrir.
    assert " OR ".join(part.strip() for part in result.split(" OR ")) == result


def test_escape_fts5_filters_stopwords() -> None:
    # Palabras interrogativas, conectores y términos que definen el corpus
    # (licitaciones, importe, total) se filtran; solo queda la keyword real.
    result = escape_fts5("¿Cuántas licitaciones de SAP hay y cuál es el importe total?")
    assert result == '"sap"'


def test_escape_fts5_strips_operators() -> None:
    result = escape_fts5("foo* -bar (baz)")
    # Operator chars stripped → tokens remain
    assert '"foo"' in result or '"baz"' in result


def test_escape_fts5_empty_string() -> None:
    assert escape_fts5("") == '""'


def test_escape_fts5_whitespace_only() -> None:
    assert escape_fts5("   ") == '""'


def test_escape_fts5_truncates_at_12_tokens() -> None:
    query = " ".join(f"word{i}" for i in range(20))
    result = escape_fts5(query)
    # El operador OR no cuenta como token de búsqueda; contamos solo las keywords.
    keyword_tokens = [t for t in result.split() if t != "OR"]
    assert len(keyword_tokens) <= 12


# ---------------------------------------------------------------------------
# faiss_search
# ---------------------------------------------------------------------------


def test_faiss_search_returns_hits_when_index_available() -> None:
    mock_index = MagicMock()
    mock_index.search.return_value = [("lic-001", 0.9), ("lic-002", 0.7)]

    faiss_module = MagicMock()
    faiss_module.FaissIndex.load.return_value = mock_index
    with patch.dict("sys.modules", {"services.faiss_index": faiss_module}):
        hits = faiss_search("consultoría", top_k=5, embedding_model="")

    assert hits == [("lic-001", 0.9), ("lic-002", 0.7)]


def test_faiss_search_returns_empty_on_exception() -> None:
    with patch.dict("sys.modules", {"services.faiss_index": None}):  # type: ignore[dict-item]
        hits = faiss_search("test", top_k=5, embedding_model="")
    assert hits == []


# ---------------------------------------------------------------------------
# fts5_search — delegates to _repo.fts5_bm25_search
# ---------------------------------------------------------------------------


def test_fts5_search_returns_normalised_scores() -> None:
    with patch(_REPO_PATH) as mock_repo:
        mock_repo.fts5_bm25_search.return_value = [("lic-A", 1.0), ("lic-B", 0.5)]
        hits = fts5_search("licitacion", top_k=5)

    assert len(hits) == 2
    ids = [h[0] for h in hits]
    assert "lic-A" in ids
    # Scores normalised to [0, 1]
    for _, score in hits:
        assert 0.0 <= score <= 1.0


def test_fts5_search_empty_rows() -> None:
    with patch(_REPO_PATH) as mock_repo:
        mock_repo.fts5_bm25_search.return_value = []
        hits = fts5_search("nothing", top_k=5)

    assert hits == []


def test_fts5_search_returns_empty_on_exception() -> None:
    with patch(_REPO_PATH) as mock_repo:
        # Repo handles exceptions internally and returns []
        mock_repo.fts5_bm25_search.return_value = []
        hits = fts5_search("test", top_k=5)
    assert hits == []


# ---------------------------------------------------------------------------
# like_search — delegates to _repo.like_fallback_search
# ---------------------------------------------------------------------------


def test_like_search_returns_hits() -> None:
    with patch(_REPO_PATH) as mock_repo:
        mock_repo.like_fallback_search.return_value = [("lic-001", 0.20), ("lic-002", 0.20)]
        hits = like_search("contrato largo palabra", top_k=10)

    assert len(hits) == 2
    for _, score in hits:
        assert score == pytest.approx(0.20)


def test_like_search_empty_query() -> None:
    hits = like_search("", top_k=5)
    assert hits == []


def test_like_search_short_tokens_fallback() -> None:
    """When all tokens < 4 chars, repo uses first token as fallback."""
    with patch(_REPO_PATH) as mock_repo:
        mock_repo.like_fallback_search.return_value = []
        hits = like_search("ab cd", top_k=5)

    assert hits == []


def test_like_search_returns_empty_on_exception() -> None:
    with patch(_REPO_PATH) as mock_repo:
        # Repo handles exceptions internally and returns []
        mock_repo.like_fallback_search.return_value = []
        hits = like_search("contrato", top_k=5)
    assert hits == []


# ---------------------------------------------------------------------------
# hybrid_rerank
# ---------------------------------------------------------------------------


def test_hybrid_rerank_combines_scores() -> None:
    faiss_hits = [("lic-A", 0.9), ("lic-B", 0.5)]
    fts_hits = [("lic-A", 0.8), ("lic-C", 0.6)]

    ranked = hybrid_rerank(faiss_hits, fts_hits, alpha=0.70, top_k=3)

    ids = [r[0] for r in ranked]
    # lic-A should be ranked first (high in both)
    assert ids[0] == "lic-A"
    assert "lic-B" in ids
    assert "lic-C" in ids


def test_hybrid_rerank_respects_top_k() -> None:
    faiss_hits = [(f"lic-{i}", float(i) / 10) for i in range(10)]
    fts_hits = [(f"lic-{i}", float(i) / 10) for i in range(10)]

    ranked = hybrid_rerank(faiss_hits, fts_hits, alpha=0.70, top_k=5)
    assert len(ranked) == 5


def test_hybrid_rerank_faiss_only() -> None:
    faiss_hits = [("lic-X", 0.9)]
    ranked = hybrid_rerank(faiss_hits, [], alpha=0.70, top_k=5)
    assert ranked[0][0] == "lic-X"


def test_hybrid_rerank_fts_only() -> None:
    fts_hits = [("lic-Y", 0.8)]
    ranked = hybrid_rerank([], fts_hits, alpha=0.70, top_k=5)
    assert ranked[0][0] == "lic-Y"


# ---------------------------------------------------------------------------
# fetch_docs — delegates to _repo.fetch_metadata_by_ids
# ---------------------------------------------------------------------------


def test_fetch_docs_returns_dict() -> None:
    doc = {
        "id_externo": "lic-001",
        "titulo": "Titulo X",
        "organo_contratacion": "Org Y",
        "importe": 1000.0,
        "descripcion": "Desc",
        "url": "http://x",
        "fecha_publicacion": "2025-01-01",
        "ccaa": "MAD",
        "estado": "VIG",
    }
    with patch(_REPO_PATH) as mock_repo:
        mock_repo.fetch_metadata_by_ids.return_value = {"lic-001": doc}
        result = fetch_docs(["lic-001"])

    assert "lic-001" in result
    assert result["lic-001"]["titulo"] == "Titulo X"


def test_fetch_docs_empty_ids() -> None:
    assert fetch_docs([]) == {}


def test_fetch_docs_filters_allowed_ids() -> None:
    with patch(_REPO_PATH) as mock_repo:
        mock_repo.fetch_metadata_by_ids.return_value = {}
        result = fetch_docs(["lic-001", "lic-002"], allowed_ids={"lic-002"})

    # Only lic-002 was allowed; repo filters internally
    assert isinstance(result, dict)
    mock_repo.fetch_metadata_by_ids.assert_called_once_with(["lic-001", "lic-002"], {"lic-002"})


def test_fetch_docs_all_filtered_by_allowed_ids() -> None:
    result = fetch_docs(["lic-001"], allowed_ids=set())
    assert result == {}


def test_fetch_docs_returns_empty_on_exception() -> None:
    with patch(_REPO_PATH) as mock_repo:
        # Repo handles exceptions internally and returns {}
        mock_repo.fetch_metadata_by_ids.return_value = {}
        result = fetch_docs(["lic-001"])
    assert result == {}


# ---------------------------------------------------------------------------
# rag_query (integration)
# ---------------------------------------------------------------------------


def test_rag_query_with_both_sources() -> None:
    faiss_hits = [("lic-001", 0.9)]
    doc = {
        "id_externo": "lic-001",
        "titulo": "T1",
        "organo_contratacion": "O1",
        "importe": 100.0,
        "descripcion": "D1",
        "url": "http://u",
        "fecha_publicacion": "2025-01-01",
        "ccaa": "MAD",
        "estado": "VIG",
    }

    faiss_module = MagicMock()
    faiss_index = MagicMock()
    faiss_index.search.return_value = faiss_hits
    faiss_module.FaissIndex.load.return_value = faiss_index

    with (
        patch.dict("sys.modules", {"services.faiss_index": faiss_module}),
        patch(_REPO_PATH) as mock_repo,
    ):
        mock_repo.fts5_bm25_search.return_value = [("lic-001", 1.0), ("lic-002", 0.5)]
        mock_repo.fetch_metadata_by_ids.return_value = {"lic-001": doc}
        docs, source = rag_query("consultoría", top_k=5)

    assert "FAISS" in source
    assert isinstance(docs, list)


def test_rag_query_falls_back_to_fts_only() -> None:
    with (
        patch.dict("sys.modules", {"services.faiss_index": None}),  # type: ignore[dict-item]
        patch(_REPO_PATH) as mock_repo,
    ):
        mock_repo.fts5_bm25_search.return_value = [("lic-A", 0.8)]
        mock_repo.fetch_metadata_by_ids.return_value = {}
        _docs, source = rag_query("test", top_k=3)

    assert "FTS5" in source


def test_rag_query_falls_back_to_like() -> None:
    with (
        patch.dict("sys.modules", {"services.faiss_index": None}),  # type: ignore[dict-item]
        patch(_REPO_PATH) as mock_repo,
    ):
        mock_repo.fts5_bm25_search.return_value = []
        mock_repo.like_fallback_search.return_value = [("lic-Z", 0.20)]
        mock_repo.fetch_metadata_by_ids.return_value = {}
        _docs, source = rag_query("consulta corta", top_k=3)

    assert "LIKE" in source
