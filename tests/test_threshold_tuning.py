"""Tests for services/threshold_tuning.py — calibration and threshold optimization."""

from __future__ import annotations

import numpy as np
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression

from services.threshold_tuning import ThresholdTuningResult, calibrate_and_tune


def _make_data(n=200, sep=1.0, random_state=42):
    X, y = make_classification(
        n_samples=n,
        n_features=10,
        class_sep=sep,
        random_state=random_state,
    )
    mid = n // 2
    return X[:mid], y[:mid], X[mid:], y[mid:]


def _fitted_estimator(X, y):
    clf = LogisticRegression(max_iter=300, random_state=0)
    clf.fit(X, y)
    return clf


def test_calibrate_and_tune_basic():
    X_tr, y_tr, X_val, y_val = _make_data(200)
    clf = _fitted_estimator(X_tr, y_tr)
    result = calibrate_and_tune(
        base_estimator=clf,
        X_train=X_tr,
        y_train=y_tr,
        X_val=X_val,
        y_val=y_val,
    )
    assert isinstance(result, ThresholdTuningResult)
    assert 0.0 <= result.threshold <= 1.0


def test_cost_sensitive_beta():
    X_tr, y_tr, X_val, y_val = _make_data(300, sep=1.5)
    clf = _fitted_estimator(X_tr, y_tr)
    r_equal = calibrate_and_tune(
        base_estimator=clf,
        X_train=X_tr,
        y_train=y_tr,
        X_val=X_val,
        y_val=y_val,
        cost_fp=1.0,
        cost_fn=1.0,
    )
    clf2 = _fitted_estimator(X_tr, y_tr)
    r_recall = calibrate_and_tune(
        base_estimator=clf2,
        X_train=X_tr,
        y_train=y_tr,
        X_val=X_val,
        y_val=y_val,
        cost_fp=1.0,
        cost_fn=25.0,
    )
    # Higher cost_fn → higher beta → lower threshold (more recall-biased)
    assert r_recall.threshold <= r_equal.threshold


def test_threshold_bounds():
    X_tr, y_tr, X_val, y_val = _make_data(200)
    clf = _fitted_estimator(X_tr, y_tr)
    for cost_fn in [0.1, 1.0, 10.0, 100.0]:
        result = calibrate_and_tune(
            base_estimator=clf,
            X_train=X_tr,
            y_train=y_tr,
            X_val=X_val,
            y_val=y_val,
            cost_fn=cost_fn,
        )
        assert 0.0 <= result.threshold <= 1.0


def test_degenerate_single_class():
    X_tr, y_tr, X_val, y_val = _make_data(200)
    y_val_all_one = np.ones_like(y_val)
    clf = _fitted_estimator(X_tr, y_tr)
    # Should not crash
    result = calibrate_and_tune(
        base_estimator=clf,
        X_train=X_tr,
        y_train=y_tr,
        X_val=X_val,
        y_val=y_val_all_one,
    )
    assert isinstance(result, ThresholdTuningResult)


def test_perfect_separation():
    X_tr, y_tr, X_val, y_val = _make_data(300, sep=5.0)
    clf = _fitted_estimator(X_tr, y_tr)
    result = calibrate_and_tune(
        base_estimator=clf,
        X_train=X_tr,
        y_train=y_tr,
        X_val=X_val,
        y_val=y_val,
    )
    assert result.fbeta >= 0.9
    assert 0.0 < result.threshold < 1.0


def test_custom_method_isotonic():
    X_tr, y_tr, X_val, y_val = _make_data(400)
    clf = _fitted_estimator(X_tr, y_tr)
    result = calibrate_and_tune(
        base_estimator=clf,
        X_train=X_tr,
        y_train=y_tr,
        X_val=X_val,
        y_val=y_val,
        method="isotonic",
    )
    assert result.method == "isotonic"
    assert 0.0 <= result.threshold <= 1.0


def test_result_fields():
    X_tr, y_tr, X_val, y_val = _make_data(200)
    clf = _fitted_estimator(X_tr, y_tr)
    result = calibrate_and_tune(
        base_estimator=clf,
        X_train=X_tr,
        y_train=y_tr,
        X_val=X_val,
        y_val=y_val,
    )
    assert hasattr(result, "threshold")
    assert hasattr(result, "fbeta")
    assert hasattr(result, "precision")
    assert hasattr(result, "recall")
    assert 0.0 <= result.precision <= 1.0
    assert 0.0 <= result.recall <= 1.0


def test_grid_populated():
    X_tr, y_tr, X_val, y_val = _make_data(200)
    clf = _fitted_estimator(X_tr, y_tr)
    result = calibrate_and_tune(
        base_estimator=clf,
        X_train=X_tr,
        y_train=y_tr,
        X_val=X_val,
        y_val=y_val,
    )
    assert isinstance(result.grid, dict)
    assert len(result.grid["threshold"]) > 0
    assert len(result.grid["fbeta"]) == len(result.grid["threshold"])
    assert len(result.grid["precision"]) == len(result.grid["threshold"])
    assert len(result.grid["recall"]) == len(result.grid["threshold"])
