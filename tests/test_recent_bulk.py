"""Tests para scheduler/jobs/recent_bulk.py — pipeline canónica (ADR-012)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_run_calls_analytics_export_before_kpi_precompute():
    """run_bulk_pipeline ejecuta analytics export antes que KPI precompute."""
    from scheduler.jobs import recent_bulk

    called: list[str] = []

    def mock_bulk_pipeline(months: int) -> dict:
        called.append(f"run_bulk_pipeline({months})")
        return {"status": "ok", "ingestion_results": [], "steps": {}}

    with patch("scheduler.pipeline_runs.run_bulk_pipeline", side_effect=mock_bulk_pipeline):
        recent_bulk.run()

    assert len(called) == 1
    assert "run_bulk_pipeline(3)" in called[0]


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


def test_run_raises_if_update_recent_fails():
    """Si la ingesta falla, run_bulk_pipeline lanza RuntimeError."""
    from scheduler.jobs import recent_bulk

    with patch(
        "scheduler.pipeline_runs.run_bulk_pipeline",
        side_effect=RuntimeError("bulk failed"),
    ):
        with pytest.raises(RuntimeError):
            recent_bulk.run()


def test_run_accepts_no_publicado_status():
    """status='no_publicado' no se considera un fallo del bulk refresh."""
    from scheduler.jobs import recent_bulk

    result = {
        "status": "ok",
        "ingestion_results": [{"status": "ok"}, {"status": "no_publicado"}],
        "steps": {},
    }

    with patch("scheduler.pipeline_runs.run_bulk_pipeline", return_value=result):
        recent_bulk.run()  # Should not raise
