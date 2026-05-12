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
        assert metrics["accuracy"] >= 0.80, (
            f"Accuracy {metrics['accuracy']:.2f} < 0.80 mínimo"
        )

    def test_f1_above_threshold(self, sample_df):
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        metrics = clf.train(sample_df)
        assert "error" not in metrics
        assert metrics["f1"] >= 0.75, f"F1 {metrics['f1']:.2f} < 0.75 mínimo"

    def test_predictions_coherent(self, sample_df):
        """Textos claramente SAP deben dar alta confianza."""
        from scraper.ml_classifier import SAPClassifier

        clf = SAPClassifier()
        clf.train(sample_df)

        # Texto claramente SAP
        is_sap, confidence = clf.predict(
            "Implantación SAP S/4HANA módulo FI/CO con ABAP"
        )
        assert is_sap is True
        assert confidence > 0.7

        # Texto claramente NO SAP
        is_sap, confidence = clf.predict(
            "Suministro de mobiliario de oficina y sillas ergonómicas"
        )
        assert is_sap is False
        assert confidence < 0.5


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
        # Primer y tercer texto deberían ser SAP
        assert results[0][0] is True
        assert results[2][0] is True
        # Segundo texto no debería ser SAP
        assert results[1][0] is False
