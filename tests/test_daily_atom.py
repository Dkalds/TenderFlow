"""Tests para scheduler/jobs/daily_atom.py — orden del pipeline (RFC 086)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _patch_common(monkeypatch_targets):
    """Context manager helper: aplica una lista de (target, mock) con patch.multiple-like."""
    return monkeypatch_targets


@pytest.fixture()
def _success_pipeline_mocks():
    """Mocks de las dependencias de daily_atom.run() con resultado exitoso."""
    mocks = {
        "update_daily": MagicMock(return_value={"status": "ok"}),
        "precompute_ml_proba": MagicMock(),
        "precompute_ml_tecnologias": MagicMock(),
        "run_analytics_export": MagicMock(return_value={"engine": "duckdb-parquet"}),
        "run_kpi_precompute": MagicMock(),
        "run_aggregates_precompute": MagicMock(),
        "check_and_notify": MagicMock(),
        "retry_failed_extractions": MagicMock(),
        "run_anomaly_checks": MagicMock(),
    }
    return mocks


def _apply_patches(mocks):
    return [
        patch("scraper.pipeline.update_daily", mocks["update_daily"]),
        patch("scraper.ml_training.precompute_ml_proba", mocks["precompute_ml_proba"]),
        patch(
            "scraper.ml_training.precompute_ml_tecnologias", mocks["precompute_ml_tecnologias"]
        ),
        patch("db.analytics.run_analytics_export", mocks["run_analytics_export"]),
        patch("scheduler.kpi_precompute.run_kpi_precompute", mocks["run_kpi_precompute"]),
        patch(
            "scheduler.aggregates_precompute.run_aggregates_precompute",
            mocks["run_aggregates_precompute"],
        ),
        patch("scheduler.watchlist_alerts.check_and_notify", mocks["check_and_notify"]),
        patch(
            "scheduler.dlq_retry.retry_failed_extractions", mocks["retry_failed_extractions"]
        ),
        patch("scheduler.anomaly_alerts.run_anomaly_checks", mocks["run_anomaly_checks"]),
    ]


def test_run_calls_analytics_export_before_kpi_precompute(_success_pipeline_mocks):
    """run_analytics_export() se invoca antes que run_kpi_precompute()."""
    from scheduler.jobs import daily_atom

    mocks = _success_pipeline_mocks
    manager = MagicMock()
    manager.attach_mock(mocks["run_analytics_export"], "run_analytics_export")
    manager.attach_mock(mocks["run_kpi_precompute"], "run_kpi_precompute")

    patches = _apply_patches(mocks)
    for p in patches:
        p.start()
    try:
        daily_atom.run()
    finally:
        for p in patches:
            p.stop()

    call_names = [c[0] for c in manager.mock_calls]
    assert "run_analytics_export" in call_names
    assert "run_kpi_precompute" in call_names
    assert call_names.index("run_analytics_export") < call_names.index("run_kpi_precompute")


def test_run_continues_when_analytics_export_raises(_success_pipeline_mocks):
    """Si run_analytics_export() lanza una excepción, el job sigue y llama run_kpi_precompute()."""
    from scheduler.jobs import daily_atom

    mocks = _success_pipeline_mocks
    mocks["run_analytics_export"] = MagicMock(side_effect=RuntimeError("boom"))

    patches = _apply_patches(mocks)
    for p in patches:
        p.start()
    try:
        daily_atom.run()
    finally:
        for p in patches:
            p.stop()

    mocks["run_analytics_export"].assert_called_once()
    mocks["run_kpi_precompute"].assert_called_once()
    mocks["run_aggregates_precompute"].assert_called_once()


def test_run_raises_if_update_daily_fails(_success_pipeline_mocks):
    """Si update_daily() no devuelve status=ok, run() lanza RuntimeError y no continúa."""
    from scheduler.jobs import daily_atom

    mocks = _success_pipeline_mocks
    mocks["update_daily"] = MagicMock(return_value={"status": "error"})

    patches = _apply_patches(mocks)
    for p in patches:
        p.start()
    try:
        with pytest.raises(RuntimeError):
            daily_atom.run()
    finally:
        for p in patches:
            p.stop()

    mocks["run_analytics_export"].assert_not_called()
    mocks["run_kpi_precompute"].assert_not_called()
