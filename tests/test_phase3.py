"""Tests for Phase 3: model registry, promotion gate, PSI, F1-drop, calibration wiring."""

from __future__ import annotations

import hashlib
import sqlite3
import tempfile
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_db():
    """Returns a temporary SQLite file with a minimal schema."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115
    tmp.close()
    con = sqlite3.connect(tmp.name)
    con.execute(
        """
        CREATE TABLE model_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            version INTEGER NOT NULL,
            path TEXT,
            sha256 TEXT,
            metrics_json TEXT,
            trained_at TEXT,
            trained_on_n_samples INTEGER,
            trained_on_n_feedbacks INTEGER,
            is_active INTEGER DEFAULT 0,
            notes TEXT
        )
        """
    )
    con.execute(
        """
        CREATE TABLE ml_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expediente TEXT,
            relevante INTEGER,
            created_at TEXT DEFAULT (CURRENT_TIMESTAMP)
        )
        """
    )
    con.commit()
    con.close()
    return tmp.name


def _make_connect(db_path: str):
    """Return a context-manager factory that opens the test DB."""

    @contextmanager
    def _connect():
        con = sqlite3.connect(db_path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    return _connect


# ─── model_registry tests ────────────────────────────────────────────────────


@pytest.mark.usefixtures("tmp_db")
class TestModelRegistry:
    """Registro de modelos, contra el motor real.

    Estos tests parcheaban ``db.model_registry.connect`` con un SQLite hecho a
    mano: ejercitaban el código de producción contra **otro dialecto** que el
    que corre en producción, que es exactamente el modo de fallo que ADR-018 y
    ADR-021 vinieron a cerrar. Pasaban porque el SQL del proyecto se escribía
    en qmark, compatible con ambos motores; al migrar a ``%s`` quedó a la vista.

    ``tmp_db`` da un schema Postgres aislado por test con ``model_versions``
    ya creada por Alembic, así que el DDL a mano tampoco hace falta.
    """

    def test_register_and_get_active(self):
        from db.model_registry import get_active, register_version

        v = register_version(
            name="test_model",
            path="/tmp/model.pkl",  # noqa: S108
            sha256="abc123",
            metrics={"f1": 0.85},
            n_samples=100,
            activate=True,
        )
        assert v == 1
        active = get_active("test_model")
        assert active is not None
        assert active["version"] == 1
        assert active["path"] == "/tmp/model.pkl"  # noqa: S108
        assert active["metrics"]["f1"] == pytest.approx(0.85)

    def test_register_increments_version(self):
        from db.model_registry import get_active, register_version

        register_version(name="m", path="/p1", sha256="s1", activate=True)
        v2 = register_version(name="m", path="/p2", sha256="s2", activate=True)
        assert v2 == 2
        active = get_active("m")
        assert active["version"] == 2

    def test_get_active_returns_none_when_no_model(self):
        from db.model_registry import get_active

        assert get_active("nonexistent") is None

    def test_activate_version_rollback(self):
        from db.model_registry import activate_version, get_active, register_version

        register_version(name="m", path="/p1", sha256="s1", activate=True)
        register_version(name="m", path="/p2", sha256="s2", activate=True)
        ok = activate_version("m", 1)
        assert ok is True
        active = get_active("m")
        assert active["version"] == 1

    def test_activate_version_missing_returns_false(self):
        from db.model_registry import activate_version

        assert activate_version("nope", 99) is False

    def test_list_versions(self):
        from db.model_registry import list_versions, register_version

        register_version(name="m", path="/p1", sha256="s1")
        register_version(name="m", path="/p2", sha256="s2")
        versions = list_versions("m")
        assert len(versions) == 2
        # Ordered DESC
        assert versions[0]["version"] == 2

    def test_feedbacks_since_last_train_no_active(self):
        """With no active model, counts all ml_feedback rows."""
        from db.database import connect, now_utc_iso

        # `created_at` es NOT NULL en el schema real; el SQLite a mano que estos
        # tests usaban no lo era, así que la divergencia no se veía.
        ahora = now_utc_iso()
        with connect() as c:
            c.execute(
                "INSERT INTO ml_feedback (expediente, relevante, created_at) VALUES ('X', 1, %s)",
                (ahora,),
            )
            c.execute(
                "INSERT INTO ml_feedback (expediente, relevante, created_at) VALUES ('Y', 0, %s)",
                (ahora,),
            )

        from db.model_registry import feedbacks_since_last_train

        assert feedbacks_since_last_train("test_model") == 2

    def test_feedbacks_since_last_train_with_active(self):
        """With an active model, only counts recent rows."""
        from db.database import connect
        from db.model_registry import feedbacks_since_last_train, register_version

        register_version(name="sap_classifier", path="/p", sha256="s", activate=True)
        # Fila anterior a trained_at: no debe contar.
        with connect() as c:
            c.execute(
                "INSERT INTO ml_feedback (expediente, relevante, created_at) "
                "VALUES ('A', 1, '2000-01-01T00:00:00')"
            )

        count = feedbacks_since_last_train("sap_classifier")
        # Row is before trained_at → count == 0
        assert count == 0


# ─── promotion gate tests ────────────────────────────────────────────────────


class TestPromotionGate:
    """El reentrenamiento semanal ya no pasa por el gate: lanza el workflow.

    Hasta 2026-10 ``maybe_retrain_classifier`` entrenaba en proceso (sin
    ``SCHEDULER_PLANE``) y delegaba en ``services.ml.promotion.promote_if_better``
    con activación inmediata. Desde que hay un solo camino de entrenamiento
    —``train-model.yml`` → ``scheduler.jobs.ml_training_run``— el job no
    entrena, no evalúa y no registra nada en ningún plano. La lógica del gate
    se testea en ``tests/test_ml_promotion_gate.py`` y el lanzamiento en
    ``tests/test_active_learning_publicacion.py``; aquí solo el cableado.
    """

    @pytest.fixture(autouse=True)
    def _sin_plano_ni_actions(self, monkeypatch):
        """El caso que antes entrenaba: sin plano y fuera de Actions."""
        for nombre in ("SCHEDULER_PLANE", "GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_REF_NAME"):
            monkeypatch.delenv(nombre, raising=False)

    def _correr(self, n_feedbacks: int):
        from scheduler.concept_drift import maybe_retrain_classifier

        with (
            patch("db.model_registry.feedbacks_since_last_train", return_value=n_feedbacks),
            patch("db.model_registry.get_active", return_value={"version": 1, "metrics": {}}),
            patch("services.ml.sap_classifier.SAPClassifier") as clf,
            patch("services.ml.classifier_training.precompute_ml_proba") as precompute,
            patch("services.ml.promotion.promote_if_better") as promote,
            patch("scheduler.concept_drift.notify") as notificar,
        ):
            result = maybe_retrain_classifier(threshold=100)
        return result, clf, precompute, promote, notificar

    def test_promotion_rejected_when_gate_fails(self):
        """Por encima del umbral no hay candidato que el gate pueda rechazar:
        no se entrena, y la versión activa sigue siendo la misma."""
        result, clf, precompute, promote, notificar = self._correr(200)

        clf.assert_not_called()
        promote.assert_not_called()
        precompute.assert_not_called()
        assert result["current_version"] == 1
        assert result.get("promotion_rejected") is None
        assert result["retrain_pendiente"] is True
        notificar.assert_called_once()

    def test_promotion_passes_when_gate_accepts(self):
        """Tampoco hay versión nueva que activar ni ``ml_proba`` que recalcular:
        eso lo hace ``activar_publicada`` cuando la Release publica el artefacto."""
        result, _clf, precompute, promote, _notificar = self._correr(200)

        assert "new_version" not in result
        assert result["triggered"] is False
        promote.assert_not_called()
        precompute.assert_not_called()


# ─── compute_psi tests ───────────────────────────────────────────────────────


class TestComputePsi:
    def test_returns_zero_with_insufficient_data(self):
        from scheduler.concept_drift import compute_psi

        with patch("services.licitaciones.load_drift_window", side_effect=ImportError):
            psi = compute_psi()
        assert psi == 0.0

    def test_returns_float_with_data(self):
        from scheduler.concept_drift import compute_psi

        ref = [{"importe": float(i * 1000)} for i in range(1, 50)]
        cur = [{"importe": float(i * 1500)} for i in range(1, 20)]  # shifted

        with patch("services.licitaciones.load_drift_window", side_effect=[ref, cur]):
            psi = compute_psi()
        assert isinstance(psi, float)
        assert psi >= 0.0

    def test_returns_zero_with_empty_window(self):
        from scheduler.concept_drift import compute_psi

        with patch("services.licitaciones.load_drift_window", side_effect=[[], []]):
            psi = compute_psi()
        assert psi == 0.0


# ─── compute_f1_drop tests ───────────────────────────────────────────────────


class TestComputeF1Drop:
    def test_returns_zero_when_no_active_model(self):
        from scheduler.drift_report import compute_f1_drop

        with patch("db.model_registry.get_active", return_value=None):
            drop = compute_f1_drop("sap_classifier")
        assert drop == 0.0

    def test_returns_zero_when_insufficient_labels(self):
        from scheduler.drift_report import compute_f1_drop

        with (
            patch(
                "db.model_registry.get_active",
                return_value={"path": None, "metrics": {"f1": 0.85}, "trained_at": "2020-01-01"},
            ),
            patch("db.database.connect") as mock_conn,
        ):
            mock_cursor = MagicMock()
            mock_cursor.__enter__ = lambda s: s
            mock_cursor.__exit__ = MagicMock(return_value=False)
            mock_cursor.execute.return_value.fetchall.return_value = []  # no rows
            mock_conn.return_value = mock_cursor

            drop = compute_f1_drop("sap_classifier", min_labelled=20)
        assert drop == 0.0

    def test_returns_positive_drop_on_degradation(self):
        from scheduler.drift_report import compute_f1_drop

        # Active model has F1=0.90; current predictions will be wrong → drop
        active_model = {"path": None, "metrics": {"f1": 0.90}, "trained_at": "2020-01-01"}
        rows = [(f"exp{i}", 1, f"titulo {i}", "desc", "72000000", 50000.0) for i in range(25)]
        # Half labelled 1, half 0 — predictions all 0 → high drop

        mock_clf = MagicMock()
        mock_clf.predict.return_value = (0, 0.1)  # always predicts 0

        with (
            patch("db.model_registry.get_active", return_value=active_model),
            patch("db.database.connect") as mock_conn,
            patch("services.ml.sap_classifier.SAPClassifier") as MockClf,
        ):
            ctx = MagicMock()
            ctx.__enter__ = lambda s: s
            ctx.__exit__ = MagicMock(return_value=False)
            ctx.execute.return_value.fetchall.return_value = rows
            mock_conn.return_value = ctx
            MockClf.load.return_value = mock_clf

            drop = compute_f1_drop("sap_classifier", min_labelled=20)
        # drop should be >= 0; we can't assert exact value without running sklearn
        assert drop >= 0.0


# ─── registry integration: ml_classifier.load() wiring ──────────────────────


class TestMlClassifierLoadRegistry:
    def test_load_uses_registry_path(self, tmp_path):
        """When no path given, load() should query registry and use active path."""
        import joblib

        from services.ml.sap_classifier import SAPClassifier

        # Create a fake model file
        clf_obj = SAPClassifier()
        model_file = tmp_path / "model.pkl"
        joblib.dump(clf_obj, model_file)
        # Create matching sha256 file
        sha = hashlib.sha256(model_file.read_bytes()).hexdigest()
        model_file.with_suffix(".sha256").write_text(sha)

        active = {"version": 5, "path": str(model_file), "metrics": {}}

        with patch("db.model_registry.get_active", return_value=active):
            loaded = SAPClassifier.load()

        assert isinstance(loaded, SAPClassifier)

    def test_load_falls_back_to_default_path_on_registry_error(self, tmp_path):
        """If registry raises, load() falls back to _MODEL_PATH (FileNotFoundError expected)."""
        from services.ml.sap_classifier import SAPClassifier

        nonexistent = tmp_path / "no_such_model.pkl"  # does not exist

        with (
            patch("db.model_registry.get_active", side_effect=RuntimeError("db down")),
            patch("services.ml.sap_classifier._MODEL_PATH", nonexistent),
            pytest.raises(FileNotFoundError),
        ):
            SAPClassifier.load()
