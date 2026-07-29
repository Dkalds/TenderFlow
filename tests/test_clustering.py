"""Tests para services.clustering_engine."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans, MiniBatchKMeans


def _make_df(n: int = 30) -> pd.DataFrame:
    """DataFrame de licitaciones sintéticas para tests."""
    rng = np.random.default_rng(42)
    titulos = [
        "Sistema ERP SAP para gestión financiera",
        "Mantenimiento aplicaciones SAP ABAP",
        "Consultoría SAP S/4HANA implantación",
        "Servicios cloud AWS infraestructura",
        "Desarrollo web portal ciudadano",
        "Soporte helpdesk usuarios finales",
    ]
    rows = []
    for i in range(n):
        base = titulos[i % len(titulos)]
        rows.append(
            {
                "id_externo": f"LIC-{i:04d}",
                "titulo": f"{base} lote {i}",
                "descripcion": f"Descripción detallada {base}",
                "organo_contratacion": f"Ministerio {i % 3}",
                "importe": float(rng.integers(10_000, 1_000_000)),
                "ccaa": "Madrid",
                "estado": "PUB",
            }
        )
    return pd.DataFrame(rows)


class TestClusterLicitaciones:
    def test_añade_columnas_cluster(self):
        from services.clustering_engine import cluster_licitaciones

        df = _make_df(30)
        result = cluster_licitaciones(df, n_clusters=3)

        assert "cluster_id" in result.columns
        assert "cluster_label" in result.columns
        assert len(result) == len(df)

    def test_numero_clusters_correcto(self):
        from services.clustering_engine import cluster_licitaciones

        df = _make_df(40)
        result = cluster_licitaciones(df, n_clusters=4)

        n_unique = result["cluster_id"].nunique()
        assert n_unique == 4

    def test_pocos_datos_devuelve_df_sin_cluster(self):
        from services.clustering_engine import cluster_licitaciones

        df = _make_df(5)  # < _MIN_ROWS = 10
        result = cluster_licitaciones(df, n_clusters=3)

        assert "cluster_id" in result.columns
        assert result["cluster_id"].nunique() == 1

    def test_df_vacio_devuelve_vacio(self):
        from services.clustering_engine import cluster_licitaciones

        df = pd.DataFrame(columns=["id_externo", "titulo", "descripcion", "importe"])
        result = cluster_licitaciones(df, n_clusters=3)

        assert len(result) == 0

    def test_labels_no_vacios(self):
        from services.clustering_engine import cluster_licitaciones

        df = _make_df(20)
        result = cluster_licitaciones(df, n_clusters=3)

        labels = result["cluster_label"].unique()
        assert all(isinstance(lb, str) and len(lb) > 0 for lb in labels)

    def test_too_few_rows(self):
        from services.clustering_engine import cluster_licitaciones

        df = pd.DataFrame({"titulo": ["a"] * 5, "descripcion": ["b"] * 5})
        result = cluster_licitaciones(df)
        assert "cluster_id" in result.columns
        assert (result["cluster_id"] == 0).all()

    def test_online_clustering(self):
        import services.clustering_engine as cl

        n = 30
        df = pd.DataFrame(
            {
                "titulo": [f"titulo {i}" for i in range(n)],
                "descripcion": [f"desc {i}" for i in range(n)],
                "id_externo": [f"id_{i}" for i in range(n)],
            }
        )
        fake_embeddings = np.random.randn(n, 10).astype(np.float32)
        with (
            patch.object(cl, "_get_embeddings", return_value=fake_embeddings),
            patch(
                "db.repositories.aggregates.AggregateRepository.load_mat_clusters", return_value=[]
            ),
        ):
            result = cl.cluster_licitaciones(df, n_clusters=3)
        assert "cluster_id" in result.columns
        assert "cluster_label" in result.columns


class TestClusterSummary:
    def test_summary_contiene_columnas_esperadas(self):
        from services.clustering_engine import cluster_licitaciones, cluster_summary

        df = _make_df(30)
        clustered = cluster_licitaciones(df, n_clusters=3)
        summary = cluster_summary(clustered)

        assert "cluster_id" in summary.columns
        assert "n" in summary.columns
        assert "importe_total" in summary.columns

    def test_summary_sin_cluster_vacio(self):
        from services.clustering_engine import cluster_summary

        df = pd.DataFrame({"titulo": ["test"], "importe": [100.0]})
        result = cluster_summary(df)
        assert result.empty

    def test_n_filas_suma_total(self):
        from services.clustering_engine import cluster_licitaciones, cluster_summary

        df = _make_df(30)
        clustered = cluster_licitaciones(df, n_clusters=3)
        summary = cluster_summary(clustered)

        assert summary["n"].sum() == len(df)

    def test_basic_summary(self):
        from services.clustering_engine import cluster_summary

        df = pd.DataFrame(
            {
                "cluster_id": [0, 0, 1],
                "cluster_label": ["a", "a", "b"],
                "id_externo": ["x", "y", "z"],
                "importe": [100, 200, 300],
            }
        )
        result = cluster_summary(df)
        assert len(result) == 2

    def test_no_cluster_id(self):
        from services.clustering_engine import cluster_summary

        df = pd.DataFrame({"a": [1]})
        assert cluster_summary(df).empty


class TestClusterKeywords:
    def test_devuelve_palabras_del_texto(self):
        from services.clustering_engine import _cluster_keywords

        texts = ["sistema SAP gestión financiera", "SAP ERP módulos financieros"] * 5
        result = _cluster_keywords(texts, top_n=3)

        assert isinstance(result, str)
        assert len(result) > 0

    def test_textos_vacios_devuelve_otros(self):
        from services.clustering_engine import _cluster_keywords

        result = _cluster_keywords([], top_n=3)
        assert result == "otros"

    def test_basic(self):
        from services.clustering_engine import _cluster_keywords

        texts = ["servicio limpieza edificio", "limpieza oficinas general"]
        result = _cluster_keywords(texts, top_n=2)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty(self):
        from services.clustering_engine import _cluster_keywords

        assert _cluster_keywords([]) == "otros"

    def test_no_valid_tokens(self):
        from services.clustering_engine import _cluster_keywords

        assert _cluster_keywords(["a b c"]) == "otros"


# ── Funciones internas adicionales (stopwords, embeddings, k-selection) ──────


class TestStopwords:
    def test_returns_frozenset(self):
        from services.clustering_engine import _stopwords

        _stopwords.cache_clear()
        result = _stopwords()
        assert isinstance(result, frozenset)

    def test_missing_file(self):
        from services.clustering_engine import _stopwords

        _stopwords.cache_clear()
        with patch("services.clustering_engine._STOPWORDS_PATH") as mock_path:
            mock_path.read_text.side_effect = OSError("missing")
            result = _stopwords()
            assert isinstance(result, frozenset)


class TestDfCacheFingerprint:
    def test_empty_df(self):
        from services.clustering_engine import _df_cache_fingerprint

        df = pd.DataFrame()
        result = _df_cache_fingerprint(df)
        assert result[0] == 0

    def test_with_data(self):
        from services.clustering_engine import _df_cache_fingerprint

        df = pd.DataFrame(
            {
                "id_externo": ["a", "b"],
                "fecha_publicacion": ["2024-01-01", "2024-02-01"],
                "importe": [100, 200],
            }
        )
        result = _df_cache_fingerprint(df)
        assert result[0] == 2


class TestTfidfEmbeddings:
    def test_returns_array(self):
        from services.clustering_engine import _tfidf_embeddings

        texts = ["hola mundo test ejemplo"] * 20
        result = _tfidf_embeddings(texts, n_features=10)
        assert isinstance(result, np.ndarray)
        assert result.shape[0] == 20


class TestGetEmbeddings:
    def test_tfidf_fallback_when_embeddings_unavailable(self):
        import services.clustering_engine as cl

        with patch.object(cl, "_tfidf_embeddings", return_value=np.zeros((5, 10))) as mock_tfidf:
            with patch("services.embeddings.embeddings_available", return_value=False):
                cl._get_embeddings(["hello world test example foo"] * 5)
        mock_tfidf.assert_called_once()


class TestKmeansFactory:
    def test_regular_kmeans(self):
        from services.clustering_engine import _kmeans_factory

        km = _kmeans_factory(3, 100)
        assert isinstance(km, KMeans)

    def test_minibatch_kmeans(self):
        from services.clustering_engine import _kmeans_factory

        km = _kmeans_factory(3, 60_000)
        assert isinstance(km, MiniBatchKMeans)


class TestKMaxFor:
    def test_small_n(self):
        from services.clustering_engine import _k_max_for

        assert _k_max_for(10) >= 2

    def test_large_n(self):
        from services.clustering_engine import _k_max_for

        result = _k_max_for(10000)
        assert result <= 20


class TestOptimalK:
    def test_finds_k(self):
        from services.clustering_engine import _optimal_k

        np.random.seed(42)
        data = np.vstack([np.random.randn(30, 5) + i * 10 for i in range(4)])
        k = _optimal_k(data, k_min=2, k_max=5)
        assert 2 <= k <= 5

    def test_kmax_less_than_kmin(self):
        from services.clustering_engine import _optimal_k

        data = np.random.randn(5, 3)
        k = _optimal_k(data, k_min=3, k_max=2)
        assert k >= 2


class TestCtfidfLabels:
    def test_basic_labels(self):
        from services.clustering_engine import _ctfidf_labels

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
        from services.clustering_engine import _ctfidf_labels

        result = _ctfidf_labels([], np.array([]))
        assert result == {}
