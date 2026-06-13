"""Tests para scheduler/jobs/daily_atom.py — pipeline canónica (ADR-012)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_run_calls_analytics_export_before_kpi_precompute():
    """La pipeline canónica ejecuta analytics export antes que KPI precompute."""
    from scheduler.jobs import daily_atom

    called: list[str] = []

    def mock_daily_pipeline() -> dict:
        called.append("run_daily_pipeline")
        return {"status": "ok", "ingestion_result": {"status": "ok"}, "steps": {}}

    with patch("scheduler.pipeline_runs.run_daily_pipeline", side_effect=mock_daily_pipeline):
        daily_atom.run()

    assert "run_daily_pipeline" in called


def test_run_continues_when_analytics_export_raises():
    """Si un paso post-ingesta falla, la pipeline canónica continúa."""
    from scheduler.pipeline_runs import _run_post_ingestion_steps

    with (
        patch(
            "scheduler.pipeline_runs._run_analytics_export",
            side_effect=RuntimeError("boom"),
        ),
        patch("scheduler.pipeline_runs._run_ml_scoring"),
        patch("scheduler.pipeline_runs._run_ml_tecnologias"),
        patch("scheduler.pipeline_runs._run_kpi_precompute"),
        patch("scheduler.pipeline_runs._run_aggregates_precompute"),
        patch("scheduler.pipeline_runs._run_watchlist_notify"),
        patch("scheduler.pipeline_runs._run_dlq_retry"),
        patch("scheduler.pipeline_runs._run_anomaly_checks"),
    ):
        results = _run_post_ingestion_steps()

    assert results["analytics_export"] == "error"
    assert results["kpi_precompute"] == "ok"


def test_run_raises_if_update_daily_fails():
    """Si la ingesta falla, run_daily_pipeline lanza RuntimeError."""
    from scheduler.jobs import daily_atom

    with patch(
        "scheduler.pipeline_runs.run_daily_pipeline",
        side_effect=RuntimeError("daily ingestion failed"),
    ):
        with pytest.raises(RuntimeError):
            daily_atom.run()
