"""Tests para scraper/ml_training.py — registro de entrenamientos y precómputo ML."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestAppendToRegistry:
    def test_creates_file_when_missing(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "sub" / "registry.json"
        _append_to_registry({"run": 1}, path=target)
        assert target.exists()
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == [{"run": 1}]

    def test_appends_to_existing(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "registry.json"
        target.write_text('[{"run": 1}]', encoding="utf-8")
        _append_to_registry({"run": 2}, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert len(data) == 2
        assert data[1]["run"] == 2

    def test_handles_corrupt_json(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "registry.json"
        target.write_text("NOT JSON", encoding="utf-8")
        _append_to_registry({"run": 1}, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == [{"run": 1}]

    def test_handles_non_list_json(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "registry.json"
        target.write_text('{"not": "a list"}', encoding="utf-8")
        _append_to_registry({"run": 1}, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == [{"run": 1}]

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        from scraper.ml_training import _append_to_registry

        target = tmp_path / "registry.json"
        target.write_text("", encoding="utf-8")
        _append_to_registry({"run": 1}, path=target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == [{"run": 1}]


class TestReadRegistry:
    def test_missing_file(self, tmp_path: Path) -> None:
        from scraper.ml_training import read_registry

        assert read_registry(path=tmp_path / "nope.json") == []

    def test_corrupt_json(self, tmp_path: Path) -> None:
        from scraper.ml_training import read_registry

        f = tmp_path / "reg.json"
        f.write_text("BAD", encoding="utf-8")
        assert read_registry(path=f) == []

    def test_non_list(self, tmp_path: Path) -> None:
        from scraper.ml_training import read_registry

        f = tmp_path / "reg.json"
        f.write_text('{"x":1}', encoding="utf-8")
        assert read_registry(path=f) == []

    def test_valid(self, tmp_path: Path) -> None:
        from scraper.ml_training import read_registry

        f = tmp_path / "reg.json"
        f.write_text('[{"a":1}]', encoding="utf-8")
        assert read_registry(path=f) == [{"a": 1}]


class TestTrainFromDb:
    @patch("db.database.connect")
    @patch("db.database.init_db")
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_train_success_saves(
        self, mock_clf_cls: MagicMock, mock_init: MagicMock, mock_connect: MagicMock
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("t1", "d1", "SAP", "48000000", 1000, "2024-01-01"),
        ]
        mock_cursor.description = [
            ("titulo",),
            ("descripcion",),
            ("raw_keywords",),
            ("cpv",),
            ("importe",),
            ("fecha_publicacion",),
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_clf = MagicMock()
        mock_clf.train.return_value = {"f1": 0.9}
        mock_clf_cls.return_value = mock_clf

        from scraper.ml_training import train_from_db

        result = train_from_db()
        mock_clf.train.assert_called_once()
        mock_clf.save.assert_called_once()

    @patch("db.database.connect")
    @patch("db.database.init_db")
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_train_error_no_save(
        self, mock_clf_cls: MagicMock, mock_init: MagicMock, mock_connect: MagicMock
    ) -> None:
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.description = [
            ("titulo",),
            ("descripcion",),
            ("raw_keywords",),
            ("cpv",),
            ("importe",),
            ("fecha_publicacion",),
        ]
        mock_conn = MagicMock()
        mock_conn.execute.return_value = mock_cursor
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_clf = MagicMock()
        mock_clf.train.return_value = {"error": "no data"}
        mock_clf_cls.return_value = mock_clf

        from scraper.ml_training import train_from_db

        result = train_from_db()
        mock_clf.save.assert_not_called()
        assert "error" in result


class TestPrecomputeMlProba:
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_no_model_available(self, mock_cls: MagicMock) -> None:
        mock_cls.is_available.return_value = False
        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result == {"updated": 0, "skipped_no_model": True}

    @patch("db.database.connect")
    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_updates_rows(
        self, mock_cls: MagicMock, mock_aug: MagicMock, mock_connect: MagicMock
    ) -> None:
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf

        import numpy as np

        mock_clf.pipeline.predict_proba.return_value = np.array([[0.2, 0.8]])

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba(batch_size=10, force=True)
        assert result["updated"] == 1
        assert result["skipped_no_model"] is False

    @patch("db.database.connect")
    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_no_rows_to_update(
        self, mock_cls: MagicMock, mock_aug: MagicMock, mock_connect: MagicMock
    ) -> None:
        mock_cls.is_available.return_value = True
        mock_cls.load.return_value = MagicMock()

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result == {"updated": 0, "skipped_no_model": False}

    @patch("scraper.ml_classifier.SAPClassifier")
    def test_load_fails(self, mock_cls: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_cls.load.side_effect = RuntimeError("corrupt")

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result == {"updated": 0, "skipped_no_model": True}

    @patch("db.database.connect")
    @patch("scraper.ml_pipeline._augment_text", side_effect=lambda t, **kw: t)
    @patch("scraper.ml_classifier.SAPClassifier")
    def test_predict_failure_continues(
        self, mock_cls: MagicMock, mock_aug: MagicMock, mock_connect: MagicMock
    ) -> None:
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf
        mock_clf.pipeline.predict_proba.side_effect = RuntimeError("boom")

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_proba

        result = precompute_ml_proba()
        assert result["updated"] == 0


class TestPrecomputeMlTecnologias:
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_no_model(self, mock_cls: MagicMock) -> None:
        mock_cls.is_available.return_value = False
        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result["skipped_no_model"] is True

    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_load_fails(self, mock_cls: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_cls.load.side_effect = RuntimeError("corrupt")
        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result["skipped_no_model"] is True

    @patch("db.database.connect")
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_no_rows(self, mock_cls: MagicMock, mock_connect: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_cls.load.return_value = MagicMock()

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result == {"updated": 0, "scores_inserted": 0, "skipped_no_model": False}

    @patch("db.database.connect")
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_updates_rows_force(self, mock_cls: MagicMock, mock_connect: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf

        mock_clf.predict_batch.return_value = [
            {
                "predicted": ["SAP", "ORACLE"],
                "max_proba": 0.9,
                "principal": "SAP",
                "scores": {"SAP": 0.9, "ORACLE": 0.7},
                "thresholds": {"SAP": 0.5, "ORACLE": 0.5},
            }
        ]

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias(force=True, batch_size=10)
        assert result["updated"] == 1
        assert result["scores_inserted"] == 2

    @patch("db.database.connect")
    @patch("scraper.tech_classifier.TechnologyClassifier")
    def test_predict_batch_failure(self, mock_cls: MagicMock, mock_connect: MagicMock) -> None:
        mock_cls.is_available.return_value = True
        mock_clf = MagicMock()
        mock_cls.load.return_value = mock_clf
        mock_clf.predict_batch.side_effect = RuntimeError("boom")

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("ext1", "titulo", "desc", "48000000", 1000),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scraper.ml_training import precompute_ml_tecnologias

        result = precompute_ml_tecnologias()
        assert result["updated"] == 0
