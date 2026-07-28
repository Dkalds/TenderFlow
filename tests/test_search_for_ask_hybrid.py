"""Tests de services/licitaciones.py::search_for_ask (plan Pliegos+RAG, F9).

Regresión central del flag: con ``RAG_HYBRID_ENABLED=False`` (default), el
comportamiento debe ser byte-a-byte idéntico al anterior — el híbrido ni
siquiera se intenta.
"""

from __future__ import annotations

from unittest.mock import patch

from services.licitaciones import _repo, search_for_ask


class TestFlagOffIsUnchanged:
    def test_hybrid_never_attempted_when_flag_off(self, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", False, raising=False)

        with (
            patch("services.licitaciones._try_hybrid_search") as mock_hybrid,
            patch.object(_repo, "search_fts_docs", return_value=[{"id_externo": "X"}]),
        ):
            docs = search_for_ask("sap basis", 5)

        mock_hybrid.assert_not_called()
        assert docs == [{"id_externo": "X"}]

    def test_fts_and_like_fallback_paths_unaffected(self, monkeypatch):
        """Sin resultados FTS, cae a LIKE — mismo comportamiento previo al flag."""
        from config import settings

        monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", False, raising=False)

        with (
            patch.object(_repo, "search_fts_docs", return_value=[]),
            patch.object(
                _repo, "search_like_for_ask", return_value=[{"id_externo": "LIKE-1"}]
            ) as mock_like,
        ):
            docs = search_for_ask("consulta rara", 5, ccaa="Madrid")

        mock_like.assert_called_once_with("consulta rara", ccaa="Madrid", limit=5)
        assert docs == [{"id_externo": "LIKE-1"}]


class TestFlagOnHybridActivation:
    def test_hybrid_results_returned_without_touching_fts(self, monkeypatch):
        from config import settings

        monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", True, raising=False)
        hybrid_docs = [{"id_externo": "HYB-1", "chunks": [{"texto": "frag"}]}]

        with (
            patch(
                "services.licitaciones._try_hybrid_search", return_value=hybrid_docs
            ) as mock_hybrid,
            patch.object(_repo, "search_fts_docs") as mock_fts,
        ):
            docs = search_for_ask("sap s/4hana", 5, ccaa="Madrid", tecnologia="SAP")

        mock_hybrid.assert_called_once_with("sap s/4hana", 5, ccaa="Madrid", tecnologia="SAP")
        mock_fts.assert_not_called()
        assert docs == hybrid_docs

    def test_hybrid_empty_falls_back_to_fts(self, monkeypatch):
        """Híbrido activo pero sin chunks aún (documento_chunks vacía) -> FTS."""
        from config import settings

        monkeypatch.setattr(settings, "RAG_HYBRID_ENABLED", True, raising=False)

        with (
            patch("services.licitaciones._try_hybrid_search", return_value=None),
            patch.object(
                _repo, "search_fts_docs", return_value=[{"id_externo": "FTS-1"}]
            ) as mock_fts,
        ):
            docs = search_for_ask("sap s/4hana", 5)

        mock_fts.assert_called_once()
        assert docs == [{"id_externo": "FTS-1"}]


class TestTryHybridSearchGating:
    def test_returns_none_when_embeddings_unavailable(self):
        from services.licitaciones import _try_hybrid_search

        with patch("services.embeddings.embeddings_available", return_value=False):
            result = _try_hybrid_search("q", 5, ccaa=None, tecnologia=None)
        assert result is None

    def test_returns_none_on_embed_failure(self):
        from services.licitaciones import _try_hybrid_search

        with (
            patch("services.embeddings.embeddings_available", return_value=True),
            patch("services.embeddings.encode_texts", side_effect=RuntimeError("no model")),
        ):
            result = _try_hybrid_search("q", 5, ccaa=None, tecnologia=None)
        assert result is None

    def test_calls_pgts_backend_with_query_embedding(self):
        from services.licitaciones import _try_hybrid_search

        fake_embedding_row = type("Row", (), {"tolist": lambda self: [0.1, 0.2]})()

        class _FakeArr(list):
            def __getitem__(self, idx):
                return fake_embedding_row if idx == 0 else super().__getitem__(idx)

        with (
            patch("services.embeddings.embeddings_available", return_value=True),
            patch("services.embeddings.encode_texts", return_value=_FakeArr([None])),
            patch("db.database.connect_read"),
            patch("db.search_backend.PgTsBackend") as mock_backend_cls,
        ):
            mock_backend_cls.return_value.hybrid_search_docs.return_value = [
                {"id_externo": "X", "chunks": []}
            ]
            result = _try_hybrid_search("pregunta", 5, ccaa="Madrid", tecnologia=None)

        assert result == [{"id_externo": "X", "chunks": []}]
        mock_backend_cls.return_value.hybrid_search_docs.assert_called_once()
        _, kwargs = mock_backend_cls.return_value.hybrid_search_docs.call_args
        assert kwargs["ccaa"] == "Madrid"
        assert kwargs["limit"] == 5
