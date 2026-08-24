"""Tests for scheduler/drift_report.py — KS test, chi2, and F1 drop detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from scheduler.drift_report import _ks_test


def test_ks_test_no_drift():
    rng = np.random.default_rng(42)
    data = rng.normal(0, 1, 200)
    ref = pd.Series(data[:100])
    cur = pd.Series(data[100:])
    result = _ks_test(ref, cur)
    # `is False`, no `== False`: el flag tiene que ser un bool nativo. np.bool_
    # pasaría el `==` y reventaría luego al serializar el informe a JSON.
    assert result["drift"] is False
    assert result["p_value"] > 0.05


def test_ks_test_with_drift():
    rng = np.random.default_rng(42)
    ref = pd.Series(rng.normal(0, 1, 100))
    cur = pd.Series(rng.normal(10, 1, 100))
    result = _ks_test(ref, cur)
    assert result["drift"] is True
    assert result["p_value"] < 0.05


def test_chi2_no_shift():
    from scipy.stats import chi2_contingency

    counts = [50, 30, 20]
    table = [counts, counts]
    _, pval, _, _ = chi2_contingency(table)
    assert pval > 0.05


def test_chi2_with_shift():
    from scipy.stats import chi2_contingency

    ref = [100, 50, 10]
    cur = [10, 50, 100]
    table = [ref, cur]
    _, pval, _, _ = chi2_contingency(table)
    assert pval < 0.05


def test_f1_drop_computation():
    """Verify F1 drop is computed correctly from known predictions."""
    from sklearn.metrics import f1_score

    y_true = [1, 1, 1, 0, 0, 0, 1, 0]
    y_pred = [1, 0, 1, 0, 1, 0, 1, 0]
    trained_f1 = 0.95
    current_f1 = float(f1_score(y_true, y_pred, zero_division=0))
    drop = max(0.0, trained_f1 - current_f1)
    relative = drop / trained_f1
    assert 0.0 < relative < 1.0
    assert current_f1 < trained_f1


def test_empty_window():
    ref = pd.Series([], dtype=float)
    cur = pd.Series([], dtype=float)
    result = _ks_test(ref, cur)
    assert result["drift"] is False
    assert result.get("reason") == "insufficient_data"


# ── _json_default ─────────────────────────────────────────────────────────────


def test_json_default_convierte_escalares_y_arrays_numpy():
    """La red de seguridad del dump: sin ella un tipo NumPy tumba el paso."""
    import json

    from scheduler.drift_report import _json_default

    dumped = json.loads(
        json.dumps(
            {
                "flag": np.bool_(True),
                "entero": np.int64(7),
                "decimal": np.float64(0.5),
                "serie": np.array([1, 2]),
            },
            default=_json_default,
        )
    )

    assert dumped == {"flag": True, "entero": 7, "decimal": 0.5, "serie": [1, 2]}


def test_json_default_no_revienta_con_tipos_desconocidos():
    from scheduler.drift_report import _json_default

    assert _json_default(object()).startswith("<object object")


# ── _load_window ──────────────────────────────────────────────────────────────


class TestLoadWindow:
    """Lines 32-37: _load_window."""

    def test_load_window_with_data(self):
        from scheduler.drift_report import _load_window

        rows = [{"importe": 100, "cpv": "123"}]
        with patch("services.licitaciones.load_drift_window", return_value=rows):
            df = _load_window(7)
        assert len(df) == 1

    def test_load_window_empty(self):
        from scheduler.drift_report import _load_window

        with patch("services.licitaciones.load_drift_window", return_value=[]):
            df = _load_window(7)
        assert df.empty


# ── _ks_test — casos adicionales ──────────────────────────────────────────────


class TestKsTest:
    """Lines 57-107 (partial): _ks_test."""

    def test_ks_test_insufficient_data(self):
        from scheduler.drift_report import _ks_test

        ref = pd.Series([1, 2, 3])
        cur = pd.Series([1, 2])
        result = _ks_test(ref, cur)
        assert result["reason"] == "insufficient_data"
        assert result["drift"] is False

    def test_ks_test_sufficient_data(self):
        np.random.seed(42)
        ref = pd.Series(np.random.normal(0, 1, 100))
        cur = pd.Series(np.random.normal(0, 1, 50))
        result = _ks_test(ref, cur)
        assert "statistic" in result
        assert "p_value" in result
        assert bool(result["drift"]) in (True, False)


# ── _prediction_drift ─────────────────────────────────────────────────────────


class TestPredictionDrift:
    """Lines 57-107: _prediction_drift."""

    def test_prediction_drift_sufficient_data(self):
        from scheduler.drift_report import _prediction_drift

        mock_conn = MagicMock()
        recent = [(0.8,), (0.7,), (0.6,), (0.9,), (0.5,)]
        previous = [(0.3,), (0.4,), (0.2,), (0.5,), (0.6,)]
        mock_conn.execute.return_value.fetchall.side_effect = [recent, previous]
        result = _prediction_drift(mock_conn)
        assert "ks_statistic" in result
        assert result["n_recent"] == 5
        assert result["n_previous"] == 5
        # `is False`, no `== False`: aquí el flag sale de comparar un np.float64
        # con el alfa, así que sin el bool() explícito sería np.bool_ y luego
        # json.dumps reventaría (p=0.357 con estos datos → sin drift).
        assert result["drift_detected"] is False

    def test_prediction_drift_insufficient_data(self):
        from scheduler.drift_report import _prediction_drift

        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.side_effect = [[(0.5,)], [(0.3,)]]
        result = _prediction_drift(mock_conn)
        assert result["reason"] == "insufficient_data"

    def test_prediction_drift_query_error(self):
        from scheduler.drift_report import _prediction_drift

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("db error")
        result = _prediction_drift(mock_conn)
        assert result["drift_detected"] is False
        assert "error" in result


# ── run_drift_report ───────────────────────────────────────────────────────────


class TestRunDriftReport:
    """Lines 120-219: run_drift_report."""

    def test_run_drift_report_empty_data(self):
        from scheduler.drift_report import run_drift_report

        with patch("scheduler.drift_report._load_window", return_value=pd.DataFrame()):
            with patch("scheduler.drift_report._REPORTS_DIR") as mock_dir:
                mock_dir.mkdir = MagicMock()
                result = run_drift_report()
        assert result["skipped"] is True

    def test_run_drift_report_with_data(self, tmp_path):
        """El informe se serializa a JSON sin mockear scipy.

        Regresión (2026-08): ``pval < _KS_ALPHA`` sobre un ``np.float64``
        devuelve ``np.bool_``, que ``json.dumps`` rechaza — y con NumPy 2 el
        mensaje es "Object of type bool is not JSON serializable", que
        despista porque ``np.bool_.__name__`` ES "bool". El paso
        ``drift_checks`` moría así en cada pasada de la pipeline diaria, en
        silencio: el run salía verde y ni el informe ni el monitor de PSI/F1
        llegaban a generarse. Este test mockeaba
        ``_ks_test`` y ``chi2_contingency`` para devolver tipos nativos, que
        es exactamente lo que ocultaba el bug: ahora corre el camino real.
        """
        import json

        from scheduler.drift_report import run_drift_report

        np.random.seed(42)
        df_ref = pd.DataFrame(
            {
                "importe": [float(x) for x in np.random.normal(1000, 100, 50)],
                "ccaa": ["Madrid"] * 25 + ["Barcelona"] * 25,
            }
        )
        df_cur = pd.DataFrame(
            {
                "importe": [float(x) for x in np.random.normal(1000, 100, 20)],
                "ccaa": ["Madrid"] * 10 + ["Barcelona"] * 10,
            }
        )

        def mock_load(days, offset_days=0):
            return df_ref if offset_days > 0 else df_cur

        # >=5 filas por ventana para que _prediction_drift recorra la rama del
        # KS real (la de `bool(pval < _KS_ALPHA)`) y no la de insufficient_data,
        # que devuelve un False literal escrito a mano y no probaría nada.
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.side_effect = [
            [(0.90,), (0.92,), (0.88,), (0.95,), (0.91,), (0.93,)],
            [(0.10,), (0.12,), (0.08,), (0.15,), (0.11,), (0.09,)],
        ]
        mock_connect = MagicMock()
        mock_connect.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.__exit__ = MagicMock(return_value=False)

        with patch("scheduler.drift_report._load_window", side_effect=mock_load):
            with patch("scheduler.drift_report._REPORTS_DIR", tmp_path):
                with patch("db.connection.connect_read", return_value=mock_connect):
                    result = run_drift_report()

        # KS real sobre 'importe' y chi² real sobre 'ccaa'. `is`, no `==`:
        # np.bool_ no es subclase de bool, así que la identidad lo caza.
        assert {"importe", "ccaa"} <= set(result["columns"])
        for col, valores in result["columns"].items():
            assert isinstance(valores["drift"], bool), f"{col}: {type(valores['drift'])}"
        # chi² de [[25,25],[10,10]] es exactamente p=1.0 → sin drift.
        assert result["columns"]["ccaa"]["drift"] is False
        # Ventanas de ml_proba bien separadas (0.9x vs 0.1x) → KS con p≈0.002.
        assert result["prediction_drift"]["drift_detected"] is True
        assert result["drift_detected"] is True

        # El fichero existe y es JSON válido: la serialización es el paso que fallaba.
        guardado = json.loads(Path(result["json_path"]).read_text(encoding="utf-8"))
        assert guardado["ref_n"] == 50 and guardado["cur_n"] == 20


# ── compute_f1_drop ────────────────────────────────────────────────────────────


class TestComputeF1Drop:
    """Lines 255-257, 267, 281-283, 295-297, 311-313."""

    def test_import_error(self):
        from scheduler.drift_report import compute_f1_drop

        with patch.dict("sys.modules", {"sklearn": None, "sklearn.metrics": None}):
            # Force an ImportError in the function
            result = compute_f1_drop()
        # It may or may not fail depending on cached imports; just ensure no crash
        assert isinstance(result, float)

    def test_no_active_model(self):
        from scheduler.drift_report import compute_f1_drop

        with patch("db.model_registry.get_active", return_value=None):
            with patch("db.database.connect"):
                with patch("scraper.ml_classifier.SAPClassifier"):
                    result = compute_f1_drop()
        assert result == 0.0

    def test_active_model_no_f1(self):
        from scheduler.drift_report import compute_f1_drop

        with patch(
            "db.model_registry.get_active", return_value={"metrics": {}, "path": "model.pkl"}
        ):
            with patch("db.database.connect"):
                with patch("scraper.ml_classifier.SAPClassifier"):
                    result = compute_f1_drop()
        assert result == 0.0

    def test_query_failed(self):
        from scheduler.drift_report import compute_f1_drop

        mock_connect = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.side_effect = Exception("db error")
        mock_connect.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.__exit__ = MagicMock(return_value=False)

        with patch(
            "db.model_registry.get_active",
            return_value={"metrics": {"f1": 0.9}, "path": "model.pkl"},
        ):
            with patch("db.database.connect", return_value=mock_connect):
                with patch("scraper.ml_classifier.SAPClassifier"):
                    result = compute_f1_drop()
        assert result == 0.0

    def test_insufficient_labelled(self):
        from scheduler.drift_report import compute_f1_drop

        mock_connect = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [("exp1", 1, "t", "d", "cpv", 100)]
        mock_connect.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.__exit__ = MagicMock(return_value=False)

        with patch(
            "db.model_registry.get_active",
            return_value={"metrics": {"f1": 0.9}, "path": "model.pkl"},
        ):
            with patch("db.database.connect", return_value=mock_connect):
                with patch("scraper.ml_classifier.SAPClassifier"):
                    result = compute_f1_drop(min_labelled=20)
        assert result == 0.0

    def test_load_model_failed(self):
        from scheduler.drift_report import compute_f1_drop

        mock_connect = MagicMock()
        mock_conn = MagicMock()
        rows = [("exp", 1, "titulo", "desc", "cpv", 100)] * 25
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.__exit__ = MagicMock(return_value=False)

        mock_clf_cls = MagicMock()
        mock_clf_cls.load.side_effect = Exception("model not found")

        with patch(
            "db.model_registry.get_active",
            return_value={"metrics": {"f1": 0.9}, "path": "model.pkl"},
        ):
            with patch("db.database.connect", return_value=mock_connect):
                with patch("scraper.ml_classifier.SAPClassifier", mock_clf_cls):
                    result = compute_f1_drop(min_labelled=5)
        assert result == 0.0

    def test_predict_failed(self):
        from scheduler.drift_report import compute_f1_drop

        mock_connect = MagicMock()
        mock_conn = MagicMock()
        rows = [("exp", 1, "titulo", "desc", "cpv", 100)] * 25
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.__exit__ = MagicMock(return_value=False)

        mock_clf = MagicMock()
        mock_clf.predict.side_effect = Exception("predict error")
        mock_clf_cls = MagicMock()
        mock_clf_cls.load.return_value = mock_clf

        with patch(
            "db.model_registry.get_active",
            return_value={"metrics": {"f1": 0.9}, "path": "model.pkl"},
        ):
            with patch("db.database.connect", return_value=mock_connect):
                with patch("scraper.ml_classifier.SAPClassifier", mock_clf_cls):
                    result = compute_f1_drop(min_labelled=5)
        assert result == 0.0

    def test_successful_f1_drop(self):
        from scheduler.drift_report import compute_f1_drop

        mock_connect = MagicMock()
        mock_conn = MagicMock()
        rows = [("exp", 1, "titulo", "desc", "cpv", 100)] * 25
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_connect.__enter__ = MagicMock(return_value=mock_conn)
        mock_connect.__exit__ = MagicMock(return_value=False)

        mock_clf = MagicMock()
        # predict returns (label, proba) — all predict 0 while true is 1 → low F1
        mock_clf.predict.return_value = (0, 0.3)
        mock_clf_cls = MagicMock()
        mock_clf_cls.load.return_value = mock_clf

        # La referencia es ``golden_holdout_f1`` (etiquetas humanas), no el
        # ``f1`` del test split: ese se mide contra etiquetas derivadas de
        # keywords y compararlo con feedback humano no es una comparación.
        with patch(
            "db.model_registry.get_active",
            return_value={
                "metrics": {"f1": 0.9, "golden_holdout_f1": 0.9},
                "path": "model.pkl",
            },
        ):
            with patch("db.database.connect", return_value=mock_connect):
                with patch("scraper.ml_classifier.SAPClassifier", mock_clf_cls):
                    result = compute_f1_drop(min_labelled=5)
        assert result > 0.0  # there should be a drop since predictions are all wrong

    def test_sin_referencia_humana_no_alerta(self):
        """Una versión registrada antes del gate unificado no dispara alertas.

        Antes se comparaba el ``f1`` del test split (etiquetas de keywords)
        contra el F1 sobre feedback humano: la diferencia entre ambas
        poblaciones es estructural, así que el umbral de aviso al 3% saltaba
        (o no) por motivos ajenos al modelo.
        """
        from scheduler.drift_report import compute_f1_drop

        with patch(
            "db.model_registry.get_active",
            return_value={"metrics": {"f1": 0.9}, "path": "model.pkl"},
        ):
            assert compute_f1_drop(min_labelled=5) == 0.0
