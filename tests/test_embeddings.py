"""Tests para services.embeddings — similitud semántica con fallback."""

from __future__ import annotations

from unittest.mock import patch


class TestSubstringMatch:
    def test_basic_match(self):
        from services.embeddings import substring_match

        corpus = [
            "Mantenimiento SAP S/4HANA y soporte técnico",
            "Servicios de limpieza oficinas",
            "Consultoría SAP migración ERP",
        ]
        results = substring_match("SAP S/4HANA soporte", corpus, threshold=0.3)
        assert len(results) > 0
        assert results[0][0] == 0

    def test_no_match(self):
        from services.embeddings import substring_match

        corpus = ["Servicios de limpieza"]
        results = substring_match("SAP HANA migración", corpus, threshold=0.5)
        assert len(results) == 0

    def test_empty_corpus(self):
        from services.embeddings import substring_match

        results = substring_match("SAP", [], threshold=0.3)
        assert results == []

    def test_empty_query(self):
        from services.embeddings import substring_match

        results = substring_match("", ["algo"], threshold=0.3)
        assert results == []


class TestSmartMatch:
    @patch("services.embeddings.embeddings_available", return_value=False)
    def test_fallback_to_substring(self, mock_avail):
        from services.embeddings import smart_match

        corpus = [
            "Implementación SAP S/4HANA",
            "Limpieza de oficinas",
        ]
        results = smart_match("SAP S/4HANA", corpus, threshold=0.5)
        assert len(results) > 0
        assert results[0][0] == 0

    @patch("services.embeddings.embeddings_available", return_value=False)
    def test_fallback_no_match(self, mock_avail):
        from services.embeddings import smart_match

        corpus = ["Limpieza de oficinas"]
        results = smart_match("SAP HANA migración", corpus, threshold=0.8)
        assert len(results) == 0


class TestEmbeddingsAvailable:
    def test_returns_bool(self):
        from services.embeddings import embeddings_available

        result = embeddings_available()
        assert isinstance(result, bool)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        import numpy as np

        from services.embeddings import cosine_similarity

        v = np.array([1.0, 0.0, 0.0])
        sim = cosine_similarity(v, v)
        assert sim.shape == (1, 1)
        assert abs(float(sim[0, 0]) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        import numpy as np

        from services.embeddings import cosine_similarity

        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        sim = cosine_similarity(a, b)
        assert abs(float(sim[0, 0])) < 1e-6

    def test_batch(self):
        import numpy as np

        from services.embeddings import cosine_similarity

        a = np.array([[1.0, 0.0], [0.0, 1.0]])
        b = np.array([[1.0, 0.0]])
        sim = cosine_similarity(a, b)
        assert sim.shape == (2, 1)
        assert abs(float(sim[0, 0]) - 1.0) < 1e-6
        assert abs(float(sim[1, 0])) < 1e-6
