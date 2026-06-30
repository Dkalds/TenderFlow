"""Tests de que no hay doble calibración según ML_USE_CALIBRATION.

El pipeline base calibra internamente (CalibratedClassifierCV) salvo cuando la
calibración la aplica una capa externa (calibrate_and_tune), en cuyo caso el
clasificador del pipeline es LogisticRegression sin envolver.
"""

from __future__ import annotations

import pytest

from config import settings


@pytest.fixture(autouse=True)
def _restore_calibration_flag():
    original = settings.ML_USE_CALIBRATION
    yield
    settings.ML_USE_CALIBRATION = original


def test_pipeline_internally_calibrated_by_default(monkeypatch) -> None:
    from sklearn.calibration import CalibratedClassifierCV

    from scraper.ml_classifier import SAPClassifier

    monkeypatch.setattr(settings, "ML_USE_CALIBRATION", False)
    clf = SAPClassifier()
    clf_step = clf.pipeline.named_steps["clf"]
    assert isinstance(clf_step, CalibratedClassifierCV)


def test_pipeline_not_internally_calibrated_when_external(monkeypatch) -> None:
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.linear_model import LogisticRegression

    from scraper.ml_classifier import SAPClassifier

    monkeypatch.setattr(settings, "ML_USE_CALIBRATION", True)
    clf = SAPClassifier()
    clf_step = clf.pipeline.named_steps["clf"]
    # Sin envoltura de calibración: el step es LogReg directamente.
    assert not isinstance(clf_step, CalibratedClassifierCV)
    assert isinstance(clf_step, LogisticRegression)


def test_make_pipeline_embeddings_respects_calibrate_flag() -> None:
    from sklearn.calibration import CalibratedClassifierCV

    from scraper.ml_pipeline import _make_pipeline_with_embeddings

    calibrated = _make_pipeline_with_embeddings(calibrate=True)
    assert isinstance(calibrated.named_steps["clf"], CalibratedClassifierCV)

    uncalibrated = _make_pipeline_with_embeddings(calibrate=False)
    assert not isinstance(uncalibrated.named_steps["clf"], CalibratedClassifierCV)
