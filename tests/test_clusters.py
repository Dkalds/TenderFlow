"""Tests para services/clusters.py — wrapper delegando a clustering_engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestClusterLicitaciones:
    def test_delegates_to_clustering_engine(self):
        import pandas as pd

        mock_cl = MagicMock()
        df = pd.DataFrame({"a": [1, 2]})
        mock_cl.return_value = df
        mock_mod = MagicMock(cluster_licitaciones=mock_cl)
        with patch.dict("sys.modules", {"services.clustering_engine": mock_mod}):
            from services.clusters import cluster_licitaciones

            result = cluster_licitaciones(df, n_clusters=5)
        mock_cl.assert_called_once_with(df, n_clusters=5)
        assert result is df

    def test_default_n_clusters(self):
        import pandas as pd

        mock_cl = MagicMock(return_value=pd.DataFrame())
        mock_mod = MagicMock(cluster_licitaciones=mock_cl)
        with patch.dict("sys.modules", {"services.clustering_engine": mock_mod}):
            from services.clusters import cluster_licitaciones

            df = pd.DataFrame({"x": [1]})
            cluster_licitaciones(df)
        mock_cl.assert_called_with(df, n_clusters=8)
