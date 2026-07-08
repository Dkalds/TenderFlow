"""Unit tests for ml_training, tech_classifier, kpi_precompute, and scheduler loop."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# ml_training — _append_to_registry / read_registry
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# ml_training — train_from_db
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# ml_training — precompute_ml_proba
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# ml_training — precompute_ml_tecnologias
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# tech_classifier — TechnologyClassifier
# ═══════════════════════════════════════════════════════════════════════════════


class TestTechnologyClassifierInit:
    def test_init_defaults(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        assert clf._trained is False
        assert isinstance(clf.labels, list)
        assert len(clf._models) == 0

    def test_predict_one_raises_untrained(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        with pytest.raises(RuntimeError, match="no entrenado"):
            clf.predict_one("test text")

    def test_predict_batch_raises_untrained(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        with pytest.raises(RuntimeError, match="no entrenado"):
            clf.predict_batch([{"text": "test"}])

    def test_predict_batch_empty(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        assert clf.predict_batch([]) == []


class TestTechnologyClassifierScoreOne:
    def test_score_one_rules_tier(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        for lbl in clf.labels:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="SAP ERP system"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.8):
                result = clf.predict_one("SAP ERP system")
        assert "scores" in result
        assert "predicted" in result

    def test_score_one_ml_tier(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.5
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.return_value = [[0.1, 0.9]]
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                result = clf.predict_one("text")
        assert result["scores"][label] == 0.9

    def test_score_one_model_none(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.5
        clf._models[label] = None
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                result = clf.predict_one("text")
        assert result["scores"][label] == 0.0

    def test_score_one_model_predict_exception(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.5
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.side_effect = RuntimeError("boom")
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                result = clf.predict_one("text")
        assert result["scores"][label] == 0.0

    def test_predict_one_no_predicted_labels(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        for lbl in clf.labels:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.1):
                result = clf.predict_one("text")
        assert result["principal"] is None
        assert result["max_proba"] == 0.1

    def test_predict_one_low_confidence(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "fragile"
        clf._thresholds[label] = 0.3
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.return_value = [[0.1, 0.9]]
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                result = clf.predict_one("text")
        assert label in result["low_confidence_techs"]


class TestTechnologyClassifierThreshold:
    def test_threshold_override(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_THRESHOLDS = {"SAP": "0.7"}
            mock_settings.ML_TECH_DEFAULT_THRESHOLD = 0.5
            result = clf._threshold_for("SAP")
        assert result == 0.7

    def test_threshold_override_invalid(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._thresholds["SAP"] = 0.6
        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_THRESHOLDS = {"SAP": "not_a_number"}
            mock_settings.ML_TECH_DEFAULT_THRESHOLD = 0.5
            result = clf._threshold_for("SAP")
        assert result == 0.6

    def test_threshold_no_override(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._thresholds["SAP"] = 0.65
        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_THRESHOLDS = {}
            mock_settings.ML_TECH_DEFAULT_THRESHOLD = 0.5
            result = clf._threshold_for("SAP")
        assert result == 0.65

    def test_threshold_none_overrides(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        with patch("scraper.tech_classifier.settings") as mock_settings:
            mock_settings.ML_TECH_THRESHOLDS = None
            mock_settings.ML_TECH_DEFAULT_THRESHOLD = 0.5
            result = clf._threshold_for("UNKNOWN_LABEL")
        assert result == 0.5


class TestTechnologyClassifierPredictBatch:
    def test_predict_batch_ml_model_exception(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.5
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.side_effect = RuntimeError("boom")
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                results = clf.predict_batch([{"text": "hello"}])
        assert len(results) == 1
        assert results[0]["scores"][label] == 0.0

    def test_predict_batch_no_predicted(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        for lbl in clf.labels:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.1):
                results = clf.predict_batch([{"text": "nothing"}])
        assert results[0]["principal"] is None
        assert results[0]["max_proba"] == 0.1

    def test_predict_batch_model_none(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "fragile"
        clf._thresholds[label] = 0.5
        clf._models[label] = None
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.5

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                results = clf.predict_batch([{"text": "hello"}])
        assert results[0]["scores"][label] == 0.0

    def test_predict_batch_with_predicted(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "ml_ready"
        clf._thresholds[label] = 0.3
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.return_value = [[0.1, 0.9]]
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                results = clf.predict_batch([{"text": "hello"}])
        assert results[0]["principal"] == label
        assert results[0]["max_proba"] == 0.9

    def test_predict_batch_fragile_low_conf(self) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        label = clf.labels[0]
        clf._tier[label] = "fragile"
        clf._thresholds[label] = 0.3
        mock_pipe = MagicMock()
        mock_pipe.predict_proba.return_value = [[0.1, 0.9]]
        clf._models[label] = mock_pipe
        for lbl in clf.labels[1:]:
            clf._tier[lbl] = "rules"
            clf._thresholds[lbl] = 0.99

        with patch("scraper.tech_classifier._augment_text", return_value="text"):
            with patch("scraper.tech_classifier._keyword_fallback_score", return_value=0.0):
                results = clf.predict_batch([{"text": "hello"}])
        assert label in results[0]["low_confidence_techs"]


class TestTechnologyClassifierPersistence:
    def test_save(self, tmp_path: Path) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        clf._trained = True
        target = tmp_path / "model.pkl"

        with patch("joblib.dump") as mock_dump:
            # Write a fake file so sha256 works
            target.write_bytes(b"fake model data")
            clf.save(path=target)
            mock_dump.assert_called_once()
        # Check sha256 sidecar was created
        sha_path = target.with_suffix(".sha256")
        assert sha_path.exists()

    def test_load_missing(self, tmp_path: Path) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        with pytest.raises(FileNotFoundError):
            TechnologyClassifier.load(path=tmp_path / "nope.pkl")

    def test_load_bad_checksum(self, tmp_path: Path) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        target = tmp_path / "model.pkl"
        target.write_bytes(b"fake model")
        sha_path = target.with_suffix(".sha256")
        sha_path.write_text("wrong_hash", encoding="utf-8")

        with pytest.raises(ValueError, match="Checksum"):
            TechnologyClassifier.load(path=target)

    def test_load_wrong_type(self, tmp_path: Path) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        target = tmp_path / "model.pkl"
        target.write_bytes(b"fake")
        # No sha file so checksum check is skipped

        with patch("joblib.load", return_value="not_a_classifier"):
            with pytest.raises(TypeError, match="no contiene"):
                TechnologyClassifier.load(path=target)

    def test_load_valid_no_sha(self, tmp_path: Path) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        target = tmp_path / "model.pkl"
        target.write_bytes(b"fake")

        mock_clf = MagicMock(spec=TechnologyClassifier)
        type(mock_clf).__name__ = "TechnologyClassifier"

        with patch("joblib.load", return_value=mock_clf):
            result = TechnologyClassifier.load(path=target)
        assert result is mock_clf

    def test_is_available(self, tmp_path: Path) -> None:
        from scraper.tech_classifier import TechnologyClassifier

        assert TechnologyClassifier.is_available(path=tmp_path / "nope.pkl") is False
        f = tmp_path / "model.pkl"
        f.write_bytes(b"x")
        assert TechnologyClassifier.is_available(path=f) is True


class TestTechnologyClassifierTrain:
    def test_missing_tecnologia_column(self) -> None:
        import pandas as pd

        from scraper.tech_classifier import TechnologyClassifier

        clf = TechnologyClassifier()
        df = pd.DataFrame({"titulo": ["a"], "descripcion": ["b"]})
        result = clf.train(df)
        assert result == {"error": "missing_tecnologia_column"}

    @patch("scraper.tech_classifier._build_multilabel_dataset")
    def test_insufficient_data(self, mock_build: MagicMock) -> None:
        import numpy as np
        import pandas as pd

        from scraper.tech_classifier import TechnologyClassifier

        mock_build.return_value = (["t"] * 5, np.zeros((5, 2)), [0, 0])
        clf = TechnologyClassifier()
        df = pd.DataFrame({"titulo": ["a"], "descripcion": ["b"], "tecnologia": ["SAP"]})
        result = clf.train(df)
        assert result["error"] == "insufficient_data"


# ═══════════════════════════════════════════════════════════════════════════════
# tech_classifier — train_from_db
# ═══════════════════════════════════════════════════════════════════════════════


class TestTechTrainFromDb:
    @patch("scraper.tech_classifier.TechnologyClassifier")
    @patch("db.connection.connect_read")
    @patch("db.connection.is_turso_backend", return_value=True)
    def test_turso_backend(
        self, mock_turso: MagicMock, mock_conn_read: MagicMock, mock_cls: MagicMock
    ) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [
            ("id1", "titulo", "desc", "48000000", 1000, "2024-01-01", "SAP", "sap"),
        ]
        mock_conn_read.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn_read.return_value.__exit__ = MagicMock(return_value=False)

        mock_instance = MagicMock()
        mock_instance.train.return_value = {"f1": 0.9}
        mock_cls.return_value = mock_instance

        from scraper.tech_classifier import train_from_db

        result = train_from_db()
        mock_instance.save.assert_called_once()

    @patch("scraper.tech_classifier.TechnologyClassifier")
    @patch("db.connection.is_turso_backend", return_value=False)
    def test_sqlite_backend(self, mock_turso: MagicMock, mock_cls: MagicMock) -> None:
        mock_instance = MagicMock()
        mock_instance.train.return_value = {"error": "no_ml_techs"}
        mock_cls.return_value = mock_instance

        with patch("sqlite3.connect") as mock_sqlite:
            mock_conn = MagicMock()
            mock_sqlite.return_value.__enter__ = MagicMock(return_value=mock_conn)
            mock_sqlite.return_value.__exit__ = MagicMock(return_value=False)
            with patch("pandas.read_sql_query") as mock_read:
                import pandas as pd

                mock_read.return_value = pd.DataFrame()

                from scraper.tech_classifier import train_from_db

                result = train_from_db()
        mock_instance.save.assert_not_called()
        assert "error" in result


# ═══════════════════════════════════════════════════════════════════════════════
# kpi_precompute
# ═══════════════════════════════════════════════════════════════════════════════


class TestComputeAllKpis:
    def test_compute_all_kpis(self) -> None:
        from scheduler.kpi_precompute import _compute_all_kpis

        mock_conn = MagicMock()

        # We need different return values for fetchone and fetchall calls.
        # fetchone returns (value,) and fetchall returns list of tuples.
        mock_conn.execute.return_value.fetchone.return_value = (42, 100.0)
        mock_conn.execute.return_value.fetchall.return_value = []

        result = _compute_all_kpis(mock_conn)
        assert isinstance(result, list)
        assert len(result) > 0
        for s in result:
            assert "computed_at" in s
            assert "metrica" in s


class TestPersistSnapshots:
    def test_persist_snapshots(self) -> None:
        from scheduler.kpi_precompute import _persist_snapshots

        mock_conn = MagicMock()
        snapshots = [
            {"computed_at": "2024-01-01", "metrica": "total", "dimension": "global", "valor": 42},
            {
                "computed_at": "2024-01-01",
                "metrica": "avg",
                "dimension": "global",
                "valor": 10.5,
                "valor_text": "x",
            },
        ]
        n = _persist_snapshots(mock_conn, snapshots)
        assert n == 2
        # 1 DELETE (execute) + 1 INSERT batch (executemany)
        assert mock_conn.execute.call_count == 1
        assert mock_conn.executemany.call_count == 1


class TestRunKpiPrecompute:
    @patch("db.database.connect")
    @patch("db.database.init_db")
    def test_run(self, mock_init: MagicMock, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (10, 50.0)
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import run_kpi_precompute

        result = run_kpi_precompute()
        assert "n_metricas" in result
        assert "elapsed_ms" in result
        assert result["n_metricas"] > 0


class TestGetLatestSnapshot:
    @patch("db.database.connect")
    def test_found(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (42, None, "2024-01-01")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_latest_snapshot

        result = get_latest_snapshot("total_licitaciones")
        assert result == {"valor": 42, "computed_at": "2024-01-01"}

    @patch("db.database.connect")
    def test_not_found(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_latest_snapshot

        result = get_latest_snapshot("total_licitaciones")
        assert result is None

    @patch("db.database.connect")
    def test_with_valor_text_json(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (None, '{"a":1}', "2024-01-01")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_latest_snapshot

        result = get_latest_snapshot("some_metric")
        assert result["valor_text"] == {"a": 1}

    @patch("db.database.connect")
    def test_with_valor_text_bad_json(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (None, "NOT JSON", "2024-01-01")
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_latest_snapshot

        result = get_latest_snapshot("some_metric")
        assert result["valor_text"] == "NOT JSON"


class TestGetAllLatest:
    @patch("db.database.connect")
    def test_empty(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (None,)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_all_latest

        assert get_all_latest() == {}

    @patch("db.database.connect")
    def test_with_data(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = ("2024-01-01",)
        mock_conn.execute.return_value.fetchall.return_value = [
            ("total", "global", 42, None),
            ("by_ccaa", "madrid", None, '{"n":10}'),
            ("bad_json", "global", None, "NOT JSON"),
        ]
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.kpi_precompute import get_all_latest

        result = get_all_latest()
        assert result["_computed_at"] == "2024-01-01"
        assert result["total"] == 42
        assert result["by_ccaa__madrid"] == {"n": 10}
        assert result["bad_json"] == "NOT JSON"


class TestExportParquet:
    @patch("db.analytics.duckdb_query")
    @patch("db.analytics.has_duckdb", return_value=True)
    def test_duckdb_export(
        self, mock_has: MagicMock, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        from scheduler.kpi_precompute import run_kpi_export_parquet

        result = run_kpi_export_parquet(output_dir=str(tmp_path))
        assert "exported" in result
        assert len(result["exported"]) == len(mock_query.call_args_list)

    @patch("db.analytics.duckdb_query", side_effect=RuntimeError("fail"))
    @patch("db.analytics.has_duckdb", return_value=True)
    def test_duckdb_query_fails(
        self, mock_has: MagicMock, mock_query: MagicMock, tmp_path: Path
    ) -> None:
        from scheduler.kpi_precompute import run_kpi_export_parquet

        result = run_kpi_export_parquet(output_dir=str(tmp_path))
        assert result["exported"] == []

    @patch("db.analytics.has_duckdb", return_value=False)
    @patch("scheduler.kpi_precompute._export_parquet_pandas_fallback")
    def test_fallback_to_pandas(self, mock_fallback: MagicMock, mock_has: MagicMock) -> None:
        mock_fallback.return_value = {"exported": [], "elapsed_ms": 0, "engine": "pandas"}
        from scheduler.kpi_precompute import run_kpi_export_parquet

        result = run_kpi_export_parquet()
        assert result["engine"] == "pandas"


# ═══════════════════════════════════════════════════════════════════════════════
# scheduler/loop.py
# ═══════════════════════════════════════════════════════════════════════════════


class TestEnvInt:
    def test_default(self) -> None:
        from scheduler.loop import _env_int

        assert _env_int("NONEXISTENT_VAR_12345", 99) == 99

    def test_from_env(self) -> None:
        from scheduler.loop import _env_int

        with patch.dict("os.environ", {"TEST_INT_VAR": "42"}):
            assert _env_int("TEST_INT_VAR", 10) == 42

    def test_invalid_value(self) -> None:
        from scheduler.loop import _env_int

        with patch.dict("os.environ", {"TEST_INT_VAR": "abc"}):
            assert _env_int("TEST_INT_VAR", 10) == 10

    def test_min_value(self) -> None:
        from scheduler.loop import _env_int

        with patch.dict("os.environ", {"TEST_INT_VAR": "0"}):
            assert _env_int("TEST_INT_VAR", 10, min_value=5) == 5


class TestBackoffInterval:
    def test_no_failures(self) -> None:
        from scheduler.loop import _backoff_interval, _consecutive_failures

        _consecutive_failures.pop("test_job", None)
        result = _backoff_interval("test_job", timedelta(minutes=10))
        assert result == timedelta(minutes=10)

    def test_with_failures(self) -> None:
        from scheduler.loop import _backoff_interval, _consecutive_failures

        _consecutive_failures["test_job_bo"] = 2
        result = _backoff_interval("test_job_bo", timedelta(minutes=10))
        assert result == timedelta(minutes=40)
        _consecutive_failures.pop("test_job_bo", None)

    def test_max_backoff(self) -> None:
        from scheduler.loop import _backoff_interval, _consecutive_failures

        _consecutive_failures["test_job_max"] = 100
        result = _backoff_interval("test_job_max", timedelta(minutes=10))
        assert result == timedelta(minutes=80)
        _consecutive_failures.pop("test_job_max", None)


class TestRunJob:
    @patch("observability.runtime_metrics.scheduler_job_duration_seconds")
    @patch("observability.runtime_metrics.scheduler_job_total")
    def test_success(self, mock_total: MagicMock, mock_dur: MagicMock) -> None:
        from scheduler.loop import _consecutive_failures, _run_job

        _consecutive_failures.pop("test_light", None)
        result = _run_job("test_light", lambda: "ok")
        assert result is True

    @patch("observability.runtime_metrics.scheduler_job_duration_seconds")
    @patch("observability.runtime_metrics.scheduler_job_total")
    @patch("scheduler.loop.notify")
    def test_failure(
        self, mock_notify: MagicMock, mock_dur: MagicMock, mock_total: MagicMock
    ) -> None:
        from scheduler.loop import _consecutive_failures, _run_job

        def _fail():
            raise RuntimeError("boom")

        result = _run_job("test_fail_job", _fail)
        assert result is False
        assert _consecutive_failures.get("test_fail_job", 0) >= 1
        _consecutive_failures.pop("test_fail_job", None)

    def test_overlap_skipped(self) -> None:
        from scheduler.loop import _active_jobs, _run_job

        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = True
        _active_jobs["test_overlap"] = fake_thread

        result = _run_job("test_overlap", lambda: None)
        assert result is False
        del _active_jobs["test_overlap"]


class TestRunDailyAtom:
    @patch("scheduler.anomaly_alerts.run_anomaly_checks")
    @patch("scheduler.dlq_retry.retry_failed_extractions")
    @patch("scheduler.watchlist_alerts.check_and_notify")
    @patch("scheduler.aggregates_precompute.run_aggregates_precompute")
    @patch("scheduler.kpi_precompute.run_kpi_precompute")
    @patch("scraper.ml_training.precompute_ml_proba")
    @patch("scraper.ml_training.precompute_ml_tecnologias")
    @patch("config.settings")
    @patch("scraper.pipeline.update_daily", return_value={"status": "ok"})
    def test_success(
        self, mock_update: MagicMock, mock_settings: MagicMock, *mocks: MagicMock
    ) -> None:
        mock_settings.ML_TECH_ENABLED = False
        # PLACSP_CONNECTOR_ENABLED (F2): un MagicMock sin este atributo seteado
        # es truthy por defecto, lo que desvía run_daily_pipeline() al path del
        # connector real (run_connector) en vez del legacy update_daily() mockeado
        # arriba -- este test verifica el path legacy explícitamente.
        mock_settings.PLACSP_CONNECTOR_ENABLED = False
        from scheduler.jobs.daily_atom import run

        run()

    @patch("scraper.pipeline.update_daily", return_value={"status": "error"})
    def test_failure(self, mock_update: MagicMock) -> None:
        from scheduler.jobs.daily_atom import run

        with pytest.raises(RuntimeError, match="daily ingestion failed"):
            run()


class TestRunRecentBulk:
    @patch("scheduler.watchlist_alerts.check_and_notify")
    @patch("scheduler.aggregates_precompute.run_aggregates_precompute")
    @patch("scheduler.kpi_precompute.run_kpi_precompute")
    @patch("scraper.pipeline.update_recent", return_value=[{"status": "ok"}])
    def test_success(self, *mocks: MagicMock) -> None:
        from scheduler.jobs.recent_bulk import run

        run()

    @patch("scraper.pipeline.update_recent", return_value=[{"status": "error"}])
    def test_failure(self, mock_update: MagicMock) -> None:
        from scheduler.jobs.recent_bulk import run

        with pytest.raises(RuntimeError, match="bulk refresh failed"):
            run()


class TestRunRecentBulkDefault:
    @patch("scheduler.watchlist_alerts.check_and_notify")
    @patch("scheduler.aggregates_precompute.run_aggregates_precompute")
    @patch("scheduler.kpi_precompute.run_kpi_precompute")
    @patch("scraper.pipeline.update_recent", return_value=[{"status": "ok"}])
    def test_reads_env(self, mock_update: MagicMock, *mocks: MagicMock) -> None:
        with patch.dict("os.environ", {"SCHEDULER_BULK_MONTHS": "5"}):
            from scheduler.jobs.recent_bulk import run

            run()
        mock_update.assert_called_once_with(5)


class TestRunRetentionCleanup:
    @patch("scheduler.retention.run_retention", return_value={"deleted": 10})
    def test_calls_retention(self, mock_retention: MagicMock) -> None:
        from scheduler.jobs.retention_cleanup import run

        result = run()
        assert result == {"deleted": 10}
        mock_retention.assert_called_once()


class TestRunWalCheckpoint:
    @patch("db.database.connect")
    def test_checkpoint(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (0, 100, 100)
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.jobs.wal_checkpoint import run

        result = run()
        assert result == {"blocked": 0, "wal_pages": 100, "checkpointed": 100}

    @patch("db.database.connect")
    def test_checkpoint_no_row(self, mock_connect: MagicMock) -> None:
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)

        from scheduler.jobs.wal_checkpoint import run

        result = run()
        assert result == {}


class TestMainLoop:
    @patch("scheduler.loop._stop_event")
    @patch("scheduler.loop.configure_tracing")
    @patch("scheduler.loop.configure_logging")
    def test_immediate_stop(
        self, mock_log_cfg: MagicMock, mock_trace: MagicMock, mock_stop: MagicMock
    ) -> None:
        from scheduler.loop import main

        mock_stop.wait.return_value = True

        with patch("scheduler.loop._run_job", return_value=True):
            result = main()

        assert result == 0
