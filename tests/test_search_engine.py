"""Tests for services/investigador/search_engine.py."""

from __future__ import annotations

from typing import Any
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

# ---------------------------------------------------------------------------
# escape_fts5 — pure function
# ---------------------------------------------------------------------------


def test_escape_fts5_simple_query() -> None:
    result = escape_fts5("contrato obra pública")
    assert '"contrato"' in result
    assert '"obra"' in result


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
    tokens = result.split()
    assert len(tokens) <= 12


# ---------------------------------------------------------------------------
# faiss_search
# ---------------------------------------------------------------------------


def test_faiss_search_returns_hits_when_index_available() -> None:
    mock_index = MagicMock()
    mock_index.search.return_value = [("lic-001", 0.9), ("lic-002", 0.7)]

    faiss_module = MagicMock()
    faiss_module.FaissIndex.load.return_value = mock_index
    with patch.dict("sys.modules", {"dashboard.faiss_index": faiss_module}):
        hits = faiss_search("consultoría", top_k=5, embedding_model="")

    assert hits == [("lic-001", 0.9), ("lic-002", 0.7)]


def test_faiss_search_returns_empty_on_exception() -> None:
    with patch.dict("sys.modules", {"dashboard.faiss_index": None}):  # type: ignore[dict-item]
        hits = faiss_search("test", top_k=5, embedding_model="")
    assert hits == []


# ---------------------------------------------------------------------------
# fts5_search
# ---------------------------------------------------------------------------


def _make_fts5_cursor(rows: list[tuple[Any, ...]]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = rows
    return cur


def test_fts5_search_returns_normalised_scores() -> None:
    rows = [("lic-A", -10.0), ("lic-B", -5.0)]
    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    conn_ctx.execute.return_value = _make_fts5_cursor(rows)

    with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
        hits = fts5_search("licitacion", top_k=5)

    assert len(hits) == 2
    ids = [h[0] for h in hits]
    assert "lic-A" in ids
    # Scores normalised to [0, 1]
    for _, score in hits:
        assert 0.0 <= score <= 1.0


def test_fts5_search_empty_rows() -> None:
    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    conn_ctx.execute.return_value = _make_fts5_cursor([])

    with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
        hits = fts5_search("nothing", top_k=5)

    assert hits == []


def test_fts5_search_returns_empty_on_exception() -> None:
    with patch("services.investigador.search_engine.connect", side_effect=RuntimeError("db error")):
        hits = fts5_search("test", top_k=5)
    assert hits == []


# ---------------------------------------------------------------------------
# like_search
# ---------------------------------------------------------------------------


def test_like_search_returns_hits() -> None:
    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    cur = MagicMock()
    cur.fetchall.return_value = [("lic-001",), ("lic-002",)]
    conn_ctx.execute.return_value = cur

    with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
        hits = like_search("contrato largo palabra", top_k=10)

    assert len(hits) == 2
    for _, score in hits:
        assert score == pytest.approx(0.20)


def test_like_search_empty_query() -> None:
    hits = like_search("", top_k=5)
    assert hits == []


def test_like_search_short_tokens_fallback() -> None:
    """When first word >= 4 chars is missing, use first token as fallback."""
    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    cur = MagicMock()
    cur.fetchall.return_value = []
    conn_ctx.execute.return_value = cur

    with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
        hits = like_search("ab cd", top_k=5)  # both tokens < 4 chars, falls back to first

    assert hits == []


def test_like_search_returns_empty_on_exception() -> None:
    with patch("services.investigador.search_engine.connect", side_effect=RuntimeError("db error")):
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
# fetch_docs
# ---------------------------------------------------------------------------


def _make_doc_cursor(rows: list[tuple[Any, ...]]) -> MagicMock:
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.description = [
        ("id_externo",),
        ("titulo",),
        ("organo_contratacion",),
        ("importe",),
        ("descripcion",),
        ("url",),
        ("fecha_publicacion",),
        ("ccaa",),
        ("estado",),
    ]
    return cur


def test_fetch_docs_returns_dict() -> None:
    row = ("lic-001", "Titulo X", "Org Y", 1000.0, "Desc", "http://x", "2025-01-01", "MAD", "VIG")
    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    conn_ctx.execute.return_value = _make_doc_cursor([row])

    with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
        result = fetch_docs(["lic-001"])

    assert "lic-001" in result
    assert result["lic-001"]["titulo"] == "Titulo X"


def test_fetch_docs_empty_ids() -> None:
    assert fetch_docs([]) == {}


def test_fetch_docs_filters_allowed_ids() -> None:
    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    conn_ctx.execute.return_value = _make_doc_cursor([])

    with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
        result = fetch_docs(["lic-001", "lic-002"], allowed_ids={"lic-002"})

    # Only lic-002 was allowed, so lic-001 was filtered; both result in empty rows here
    assert isinstance(result, dict)


def test_fetch_docs_all_filtered_by_allowed_ids() -> None:
    result = fetch_docs(["lic-001"], allowed_ids=set())
    assert result == {}


def test_fetch_docs_returns_empty_on_exception() -> None:
    with patch("services.investigador.search_engine.connect", side_effect=RuntimeError("db down")):
        result = fetch_docs(["lic-001"])
    assert result == {}


# ---------------------------------------------------------------------------
# rag_query (integration)
# ---------------------------------------------------------------------------


def test_rag_query_with_both_sources() -> None:
    faiss_hits = [("lic-001", 0.9)]
    fts_hits = [("lic-001", 0.8), ("lic-002", 0.5)]
    doc_row = ("lic-001", "T1", "O1", 100.0, "D1", "http://u", "2025-01-01", "MAD", "VIG")

    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)

    faiss_module = MagicMock()
    faiss_index = MagicMock()
    faiss_index.search.return_value = faiss_hits
    faiss_module.FaissIndex.load.return_value = faiss_index

    fts_cursor = MagicMock()
    fts_cursor.fetchall.return_value = [("lic-001", -10.0), ("lic-002", -5.0)]

    doc_cursor = _make_doc_cursor([doc_row])
    conn_ctx.execute.side_effect = [fts_cursor, doc_cursor]

    with patch.dict("sys.modules", {"dashboard.faiss_index": faiss_module}):
        with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
            docs, source = rag_query("consultoría", top_k=5)

    assert "FAISS" in source
    assert isinstance(docs, list)


def test_rag_query_falls_back_to_fts_only() -> None:
    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    fts_cursor = MagicMock()
    fts_cursor.fetchall.return_value = [("lic-A", -8.0)]
    doc_cursor = _make_doc_cursor([])
    conn_ctx.execute.side_effect = [fts_cursor, doc_cursor]

    with patch.dict("sys.modules", {"dashboard.faiss_index": None}):  # type: ignore[dict-item]
        with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
            docs, source = rag_query("test", top_k=3)

    assert "FTS5" in source


def test_rag_query_falls_back_to_like() -> None:
    conn_ctx = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn_ctx)
    conn_ctx.__exit__ = MagicMock(return_value=False)

    fts_cursor = MagicMock()
    fts_cursor.fetchall.return_value = []

    like_cursor = MagicMock()
    like_cursor.fetchall.return_value = [("lic-Z",)]

    doc_cursor = _make_doc_cursor([])
    conn_ctx.execute.side_effect = [fts_cursor, like_cursor, doc_cursor]

    with patch.dict("sys.modules", {"dashboard.faiss_index": None}):  # type: ignore[dict-item]
        with patch("services.investigador.search_engine.connect", return_value=conn_ctx):
            docs, source = rag_query("consulta corta", top_k=3)

    assert "LIKE" in source
