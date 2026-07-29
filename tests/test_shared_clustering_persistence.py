"""Tests para shared/clustering_persistence.py — save/load de modelos de clustering."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch


def save_clustering_helper(**kwargs):
    """Helper to call save_clustering with proper imports."""
    from shared.clustering_persistence import save_clustering

    return save_clustering(**kwargs)


class TestClusteringPersistence:
    @patch("shared.clustering_persistence.register_version", return_value=42)
    @patch("shared.clustering_persistence.joblib")
    @patch("shared.clustering_persistence.np")
    def test_save_clustering_with_centroids(self, mock_np, mock_joblib, mock_register):
        model = MagicMock()
        model.cluster_centers_ = [[1, 2], [3, 4]]
        model.n_clusters = 2
        type(model).__name__ = "KMeans"
        vec = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Make joblib.dump actually create the file so _sha256_file works
            def fake_dump(bundle, path, compress=3):
                Path(path).write_bytes(b"fake")

            mock_joblib.dump.side_effect = fake_dump

            result = save_clustering_helper(
                model=model,
                vectorizer=vec,
                dataset_hash="abc",
                metrics={"s": 0.5},
                n_samples=100,
                base_dir=tmpdir,
                activate=True,
            )

        assert result["version"] == 42
        assert result["algorithm"] == "KMeans"
        assert result["n_clusters"] == 2
        mock_register.assert_called_once()

    @patch("shared.clustering_persistence.register_version", return_value=1)
    @patch("shared.clustering_persistence.joblib")
    @patch("shared.clustering_persistence.np")
    def test_save_clustering_no_centroids(self, mock_np, mock_joblib, mock_register):
        model = MagicMock(spec=[])  # no cluster_centers_
        model.n_clusters = 3
        type(model).__name__ = "FakeModel"

        # Make sure getattr returns None for cluster_centers_
        # spec=[] means no attributes, so getattr(model, 'cluster_centers_', None) -> None

        with tempfile.TemporaryDirectory() as tmpdir:

            def fake_dump(bundle, path, compress=3):
                Path(path).write_bytes(b"data")

            mock_joblib.dump.side_effect = fake_dump

            result = save_clustering_helper(
                model=model,
                vectorizer=None,
                dataset_hash="xyz",
                base_dir=tmpdir,
                activate=False,
            )

        assert result["centroids_path"] is None
        mock_np.save.assert_not_called()

    @patch("shared.clustering_persistence.get_active", return_value=None)
    def test_load_clustering_no_active(self, mock_get):
        from shared.clustering_persistence import load_clustering

        result = load_clustering()
        assert result == (None, None)

    @patch("shared.clustering_persistence.get_active")
    def test_load_clustering_missing_file(self, mock_get):
        mock_get.return_value = {"path": "/nonexistent/file.joblib"}
        from shared.clustering_persistence import load_clustering

        model, meta = load_clustering()
        assert model is None
        assert meta is not None

    @patch("shared.clustering_persistence.joblib")
    @patch("shared.clustering_persistence.get_active")
    def test_load_clustering_load_error(self, mock_get, mock_joblib):
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
            f.write(b"x")
            fpath = f.name
        try:
            mock_get.return_value = {"path": fpath}
            mock_joblib.load.side_effect = EOFError("bad")
            from shared.clustering_persistence import load_clustering

            model, meta = load_clustering()
            assert model is None
            assert meta is not None
        finally:
            os.unlink(fpath)

    @patch("shared.clustering_persistence.joblib")
    @patch("shared.clustering_persistence.get_active")
    def test_load_clustering_success(self, mock_get, mock_joblib):
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as f:
            f.write(b"x")
            fpath = f.name
        try:
            mock_get.return_value = {"path": fpath}
            bundle = {"model": "km", "vectorizer": "vec"}
            mock_joblib.load.return_value = bundle
            from shared.clustering_persistence import load_clustering

            model, _meta = load_clustering()
            assert model is bundle
        finally:
            os.unlink(fpath)
