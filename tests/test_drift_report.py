"""Tests for scheduler/drift_report.py — KS test, chi2, and F1 drop detection."""

from __future__ import annotations

import numpy as np
import pandas as pd

from scheduler.drift_report import _ks_test


def test_ks_test_no_drift():
    rng = np.random.default_rng(42)
    data = rng.normal(0, 1, 200)
    ref = pd.Series(data[:100])
    cur = pd.Series(data[100:])
    result = _ks_test(ref, cur)
    assert result["drift"] == False  # noqa: E712 — numpy bool
    assert result["p_value"] > 0.05


def test_ks_test_with_drift():
    rng = np.random.default_rng(42)
    ref = pd.Series(rng.normal(0, 1, 100))
    cur = pd.Series(rng.normal(10, 1, 100))
    result = _ks_test(ref, cur)
    assert result["drift"] == True  # noqa: E712 — numpy bool
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
    assert result["drift"] == False  # noqa: E712 — numpy bool
    assert result.get("reason") == "insufficient_data"
