"""Helpers puros de clustering de ``services.analytics.clusters``."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
from sklearn.cluster import KMeans, MiniBatchKMeans


class TestStopwords:
    def test_returns_frozenset(self):
        from services.analytics.clusters import _stopwords

        _stopwords.cache_clear()
        result = _stopwords()
        assert isinstance(result, tuple)

    def test_missing_file(self):
        from services.analytics.clusters import _stopwords

        _stopwords.cache_clear()
        with patch("services.analytics.clusters._STOPWORDS_PATH") as mock_path:
            mock_path.read_text.side_effect = OSError("missing")
            result = _stopwords()
            assert isinstance(result, tuple)


class TestTfidfEmbeddings:
    def test_returns_array(self):
        from services.analytics.clusters import _tfidf_embeddings

        texts = ["hola mundo test ejemplo"] * 20
        result = _tfidf_embeddings(texts, n_features=10)
        assert isinstance(result, np.ndarray)
        assert result.shape[0] == 20


class TestKmeansFactory:
    def test_regular_kmeans(self):
        from services.analytics.clusters import _kmeans_factory

        km = _kmeans_factory(3, 100)
        assert isinstance(km, KMeans)

    def test_minibatch_kmeans(self):
        from services.analytics.clusters import _kmeans_factory

        km = _kmeans_factory(3, 60_000)
        assert isinstance(km, MiniBatchKMeans)


class TestKMaxFor:
    def test_small_n(self):
        from services.analytics.clusters import _k_max_for

        assert _k_max_for(10) >= 2

    def test_large_n(self):
        from services.analytics.clusters import _k_max_for

        result = _k_max_for(10000)
        assert result <= 20


class TestOptimalK:
    def test_finds_k(self):
        from services.analytics.clusters import _optimal_k

        np.random.seed(42)
        data = np.vstack([np.random.randn(30, 5) + i * 10 for i in range(4)])
        k = _optimal_k(data, k_min=2, k_max=5)
        assert 2 <= k <= 5

    def test_kmax_less_than_kmin(self):
        from services.analytics.clusters import _optimal_k

        data = np.random.randn(5, 3)
        k = _optimal_k(data, k_min=3, k_max=2)
        assert k >= 2


class TestCtfidfLabels:
    def test_basic_labels(self):
        from services.analytics.clusters import _ctfidf_labels

        texts = [
            "servicio limpieza edificio",
            "limpieza oficinas limpieza",
            "desarrollo software aplicacion",
            "software desarrollo sistema",
        ]
        labels = np.array([0, 0, 1, 1])
        result = _ctfidf_labels(texts, labels, top_n=2)
        assert 0 in result
        assert 1 in result

    def test_empty_labels(self):
        from services.analytics.clusters import _ctfidf_labels

        result = _ctfidf_labels([], np.array([]))
        assert result == {}
