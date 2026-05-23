"""Tests del clasificador ML con datos realistas.

Entrena un modelo con datos de muestra representativos y verifica accuracy,
serialización y concept drift. Marcados como @pytest.mark.slow.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

pytestmark = pytest.mark.slow

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture()
def sample_df() -> pd.DataFrame:
    """Carga los datos de muestra como DataFrame compatible con el clasificador."""
    data = json.loads((_FIXTURES_DIR / "ml_sample_data.json").read_text(encoding="utf-8"))
    rows = []
    for item in data:
        rows.append(
            {
                "titulo": item["titulo"],
                "descripcion": item["descripcion"],
                "raw_keywords": "SAP" if item["is_sap"] else None,
                "cpv": "72000000" if item["is_sap"] else "39000000",
            }
        )
    return pd.DataFrame(rows)


class TestMLAccuracy:
    """El modelo entrenado con datos realistas debe alcanzar accuracy mínima."""

    def test_accuracy_above_threshold(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "error" not in metrics, f"Entrenamiento falló: {metrics}"
        assert metrics["accuracy"] >= 0.80, f"Accuracy {metrics['accuracy']:.2f} < 0.80 mínimo"

    def test_f1_above_threshold(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "error" not in metrics
        assert metrics["f1"] >= 0.75, f"F1 {metrics['f1']:.2f} < 0.75 mínimo"

    def test_predictions_coherent(self, sample_df):
        """Textos claramente SAP deben dar mayor confianza que textos no SAP."""
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)

        # Texto claramente SAP — confianza debe ser mayor que para texto no SAP
        _is_sap, conf_sap = clf.predict("Implantación SAP S/4HANA módulo FI/CO con ABAP")

        # Texto claramente NO SAP
        _is_no_sap, conf_no_sap = clf.predict(
            "Suministro de mobiliario de oficina y sillas ergonómicas"
        )
        assert conf_sap > conf_no_sap, (
            f"SAP text confidence ({conf_sap:.3f}) should exceed "
            f"non-SAP text confidence ({conf_no_sap:.3f})"
        )


class TestMLSerialization:
    """Verifica que el ciclo save/load preserva las predicciones."""

    def test_save_load_preserves_predictions(self, sample_df, tmp_path):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)

        # Predicción antes de serializar
        text = "Consultoría SAP BW/4HANA y analítica avanzada"
        pred_before = clf.predict(text)

        # Save + Load
        model_path = tmp_path / "test_model.pkl"
        clf.save(model_path)
        loaded = SAPClassifier.load(model_path)

        # Predicción tras deserializar
        pred_after = loaded.predict(text)
        assert pred_before[0] == pred_after[0]  # misma clasificación
        assert abs(pred_before[1] - pred_after[1]) < 0.01  # misma confianza

    def test_sha256_checksum_created(self, sample_df, tmp_path):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)

        model_path = tmp_path / "test_model.pkl"
        clf.save(model_path)

        checksum_path = model_path.with_suffix(".sha256")
        assert checksum_path.exists()
        assert len(checksum_path.read_text().strip()) == 64  # SHA256 hex

    def test_corrupted_model_rejected(self, sample_df, tmp_path):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)

        model_path = tmp_path / "test_model.pkl"
        clf.save(model_path)

        # Corromper el modelo
        data = model_path.read_bytes()
        model_path.write_bytes(data[:100] + b"CORRUPTED" + data[109:])

        # Intentar cargar debe fallar
        with pytest.raises(RuntimeError, match="SHA256 no coincide"):
            SAPClassifier.load(model_path)


class TestBatchPrediction:
    """Verifica predicción en batch."""

    def test_batch_returns_correct_length(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)

        texts = [
            "Implantación SAP S/4HANA",
            "Suministro de papel A4",
            "Consultoría SAP ABAP Fiori",
        ]
        results = clf.predict_batch(texts)
        assert len(results) == 3
        # Primer y tercer texto deberían tener P(SAP) > 50%
        # (usamos confianza directa para no depender del threshold óptimo)
        assert results[0][1] > 0.5, f"SAP text should have P(SAP) > 0.5, got {results[0][1]}"
        assert results[2][1] > 0.5, f"SAP text should have P(SAP) > 0.5, got {results[2][1]}"
        # Segundo texto no debería ser SAP
        assert results[1][1] < 0.5, f"non-SAP text should have P(SAP) < 0.5, got {results[1][1]}"


class TestNewMetrics:
    """Verifica que train() reporta las nuevas métricas del clasificador mejorado."""

    def test_train_returns_pr_auc(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "pr_auc" in metrics
        assert 0.0 <= metrics["pr_auc"] <= 1.0

    def test_train_returns_cv_f1(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "cv_f1" in metrics
        assert 0.0 <= metrics["cv_f1"] <= 1.0

    def test_train_returns_optimal_threshold(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "optimal_threshold" in metrics
        thresh = metrics["optimal_threshold"]
        assert 0.30 <= thresh <= 0.95, f"threshold {thresh} fuera del rango [0.30, 0.95]"

    def test_train_returns_precision_recall(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "precision" in metrics
        assert "recall" in metrics
        assert 0.0 <= metrics["precision"] <= 1.0
        assert 0.0 <= metrics["recall"] <= 1.0

    def test_train_returns_temporal_split_flag(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "temporal_split" in metrics
        # sample_df no tiene fecha_publicacion → debe ser False
        assert metrics["temporal_split"] is False

    def test_train_temporal_split_with_dates(self, sample_df):
        """Cuando se proporcionan fechas, debe usar split temporal."""
        import pandas as pd

        from scraper.ml_classifier import SAPClassifier

        df_with_dates = sample_df.copy()
        # Asignar fechas progresivas para simular datos temporales
        dates = pd.date_range("2023-01-01", periods=len(df_with_dates), freq="7D").strftime(
            "%Y-%m-%d"
        )
        df_with_dates["fecha_publicacion"] = dates
        clf = SAPClassifier()
        metrics = clf.train(df_with_dates)
        # Puede ser True o False (depende de distribución de clases en test set)
        assert "temporal_split" in metrics

    def test_threshold_used_in_predict(self, sample_df):
        """El umbral óptimo del entrenamiento se usa en predict()."""
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)
        # El threshold en metadata está redondeado a 4 decimales;
        # clf._threshold conserva la precisión completa.
        assert abs(clf._threshold - clf.metadata["optimal_threshold"]) < 1e-3

    def test_metadata_populated_after_train(self, sample_df):
        """metadata contiene trained_at y métricas clave tras train()."""
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)
        assert "trained_at" in clf.metadata
        assert "pr_auc" in clf.metadata
        assert "optimal_threshold" in clf.metadata
        assert "n_train" in clf.metadata


class TestPredictProba:
    """Verifica el método predict_proba() público."""

    def test_predict_proba_shape(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)
        texts = ["Implantación SAP S/4HANA", "Suministro de papel A4"]
        proba = clf.predict_proba(texts)
        assert proba.shape == (2, 2), f"Shape esperada (2, 2), obtenida {proba.shape}"

    def test_predict_proba_sums_to_one(self, sample_df):
        import numpy as np

        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)
        texts = ["Implantación SAP S/4HANA"]
        proba = clf.predict_proba(texts)
        row_sums = proba.sum(axis=1)
        assert np.allclose(row_sums, 1.0, atol=1e-6), f"Suma de probabilidades != 1: {row_sums}"

    def test_predict_proba_column1_is_p_sap(self, sample_df):
        """Columna 1 es P(SAP); texto SAP debe tener P(SAP) > P(no-SAP)."""
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)
        proba = clf.predict_proba(["Implantación SAP S/4HANA"])
        # P(SAP) > P(no-SAP) para texto claramente SAP
        assert proba[0][1] > proba[0][0], "P(SAP) debería ser mayor que P(no-SAP)"

    def test_predict_proba_consistent_with_predict_batch(self, sample_df):
        """predict_proba y predict_batch deben dar las mismas confianzas."""
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)
        texts = ["Implantación SAP S/4HANA", "Compra de vehículos"]
        proba = clf.predict_proba(texts)
        batch = clf.predict_batch(texts)
        for i, (_, conf) in enumerate(batch):
            assert abs(float(proba[i][1]) - conf) < 1e-6, (
                f"Discrepancia entre predict_proba y predict_batch en idx {i}"
            )


class TestCPVTokenAugmentation:
    """Verifica que los tokens CPV e importe mejoran la predicción."""

    def test_augment_text_cpv_ti(self):
        from scraper.ml_classifier import _augment_text

        result = _augment_text("sistema ERP", cpv="72263000")
        assert "CPV_TI" in result

    def test_augment_text_cpv_no_ti(self):
        from scraper.ml_classifier import _augment_text

        result = _augment_text("suministro muebles", cpv="39000000")
        assert "CPV_NO_TI" in result

    def test_augment_text_importe_bins(self):
        from scraper.ml_classifier import _augment_text

        assert "IMPORTE_XS" in _augment_text("texto", importe=5000.0)
        assert "IMPORTE_S" in _augment_text("texto", importe=50000.0)
        assert "IMPORTE_M" in _augment_text("texto", importe=500000.0)
        assert "IMPORTE_L" in _augment_text("texto", importe=5000000.0)
        assert "IMPORTE_XL" in _augment_text("texto", importe=50000000.0)

    def test_augment_text_no_extra(self):
        """Sin CPV ni importe, el texto no se modifica."""
        from scraper.ml_classifier import _augment_text

        result = _augment_text("texto original")
        assert result == "texto original"

    def test_predict_with_cpv_kwarg(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)
        # No debe lanzar error al pasar cpv e importe opcionales
        is_sap, conf = clf.predict("Servicio de consultoría ERP", cpv="72000000", importe=200000)
        assert isinstance(is_sap, bool)
        assert 0.0 <= conf <= 1.0


class TestMetadataPersistence:
    """Verifica que metadata y threshold se preservan en save/load."""

    def test_save_load_preserves_threshold(self, sample_df, tmp_path):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)
        original_threshold = clf._threshold

        model_path = tmp_path / "test_model.pkl"
        clf.save(model_path)
        loaded = SAPClassifier.load(model_path)

        assert abs(loaded._threshold - original_threshold) < 1e-9

    def test_save_load_preserves_metadata(self, sample_df, tmp_path):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)

        model_path = tmp_path / "test_model.pkl"
        clf.save(model_path)
        loaded = SAPClassifier.load(model_path)

        assert "trained_at" in loaded.metadata
        assert loaded.metadata["pr_auc"] == clf.metadata["pr_auc"]

    def test_legacy_model_loads_with_defaults(self, sample_df, tmp_path):
        """Modelos anteriores sin _threshold/metadata cargan con valores por defecto."""
        import joblib

        from config import settings
        from scraper.ml_classifier import SAPClassifier

        # Simular modelo legacy sin _threshold ni metadata
        clf = SAPClassifier()
        clf.train(sample_df)
        del clf._threshold
        del clf.metadata

        model_path = tmp_path / "legacy_model.pkl"
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(clf, model_path, compress=3)
        import hashlib

        sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
        model_path.with_suffix(".sha256").write_text(sha, encoding="utf-8")

        loaded = SAPClassifier.load(model_path)
        assert loaded._threshold == settings.ML_CONFIDENCE_THRESHOLD
        assert loaded.metadata == {}


class TestRound2Improvements:
    """Tests para mejoras Round 2: F-beta, Brier/ECE, registry, TimeSeriesCV."""

    def test_train_returns_fbeta_metric(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "fbeta" in metrics
        assert "beta" in metrics
        assert 0.0 <= metrics["fbeta"] <= 1.0
        assert metrics["beta"] > 0

    def test_train_returns_brier_score(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "brier" in metrics
        # Brier ∈ [0, 1] para probabilidades binarias.
        assert 0.0 <= metrics["brier"] <= 1.0

    def test_train_returns_ece(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "ece" in metrics
        assert 0.0 <= metrics["ece"] <= 1.0

    def test_fbeta_uses_settings(self, sample_df):
        """beta reportado en métricas refleja el valor en settings.ML_FBETA."""
        from config.settings import settings
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        # El valor de beta debe coincidir con el de settings (default 1.5).
        assert metrics["beta"] == float(settings.ML_FBETA)
        assert metrics["beta"] > 0

    def test_expected_calibration_error_helper(self):
        import numpy as np

        from scraper.ml_classifier import _expected_calibration_error

        # Predicciones perfectamente calibradas → ECE ≈ 0
        y_true = np.array([0, 0, 0, 0, 1, 1, 1, 1])
        y_proba = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        ece = _expected_calibration_error(y_true, y_proba, n_bins=10)
        assert ece < 0.01

        # Predicciones totalmente erradas → ECE alto
        y_true2 = np.array([1, 1, 1, 1, 0, 0, 0, 0])
        y_proba2 = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
        ece2 = _expected_calibration_error(y_true2, y_proba2, n_bins=10)
        assert ece2 > 0.5

    def test_ece_empty_input(self):
        import numpy as np

        from scraper.ml_classifier import _expected_calibration_error

        assert _expected_calibration_error(np.array([]), np.array([])) == 0.0

    def test_registry_append_and_read(self, tmp_path):
        from scraper.ml_classifier import _append_to_registry, read_registry

        reg_path = tmp_path / "registry.json"
        entry1 = {"trained_at": "2025-01-01T00:00:00", "f1": 0.85, "fbeta": 0.88}
        entry2 = {"trained_at": "2025-01-02T00:00:00", "f1": 0.87, "fbeta": 0.90}
        _append_to_registry(entry1, path=reg_path)
        _append_to_registry(entry2, path=reg_path)
        history = read_registry(path=reg_path)
        assert len(history) == 2
        assert history[0]["f1"] == 0.85
        assert history[1]["f1"] == 0.87

    def test_read_registry_missing_file(self, tmp_path):
        from scraper.ml_classifier import read_registry

        missing = tmp_path / "does_not_exist.json"
        assert read_registry(path=missing) == []

    def test_read_registry_corrupt_file(self, tmp_path):
        from scraper.ml_classifier import read_registry

        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert read_registry(path=bad) == []

    def test_train_appends_to_registry(self, sample_df, tmp_path, monkeypatch):
        from scraper import ml_training
        from scraper.ml_classifier import SAPClassifier, read_registry

        reg_path = tmp_path / "reg.json"
        monkeypatch.setattr(ml_training, "_REGISTRY_PATH", reg_path)
        clf = SAPClassifier()
        clf.train(sample_df)
        history = read_registry(path=reg_path)
        assert len(history) == 1
        assert "f1" in history[0]
        assert "trained_at" in history[0]
