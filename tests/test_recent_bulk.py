"""Tests para scheduler/jobs/recent_bulk.py — pipeline canónica (ADR-012)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


def test_partial_failure_runs_post_ingestion_and_reports_degraded():
    """Un mes fallido no aborta la pipeline: corre post-ingesta y reporta degraded."""
    from scheduler.pipeline_runs import run_bulk_pipeline

    results = [
        {"year": 2026, "month": 5, "status": "ok", "nuevas": 3, "actualizadas": 1},
        {"year": 2026, "month": 6, "status": "error_descarga"},
    ]

    with (
        patch("scraper.pipeline.update_recent", return_value=results),
        patch(
            "scheduler.pipeline_runs._run_post_ingestion_steps",
            return_value={"dlq_retry": "ok"},
        ) as mock_steps,
        patch("scheduler.pipeline_runs._notify_degraded") as mock_notify,
    ):
        out = run_bulk_pipeline(months=2)

    mock_steps.assert_called_once()  # dlq_retry etc. sí corren
    mock_notify.assert_called_once()
    assert out["status"] == "degraded"
    assert out["failed_months"] == [{"year": 2026, "month": 6, "status": "error_descarga"}]


def test_total_failure_raises_runtimeerror():
    """Si fallan todos los meses, se lanza RuntimeError (fatal genuino)."""
    from scheduler.pipeline_runs import run_bulk_pipeline

    results = [
        {"year": 2026, "month": 5, "status": "error_descarga"},
        {"year": 2026, "month": 6, "status": "error_descarga"},
    ]

    with (
        patch("scraper.pipeline.update_recent", return_value=results),
        patch("scheduler.pipeline_runs._run_post_ingestion_steps") as mock_steps,
    ):
        with pytest.raises(RuntimeError, match="all 2 month"):
            run_bulk_pipeline(months=2)

    mock_steps.assert_not_called()  # no hay nada que post-procesar


def test_run_update_returns_1_on_degraded():
    """run_update.main devuelve 1 (no fatal) cuando el bulk queda degradado."""
    pipeline_result = {
        "status": "degraded",
        "ingestion_results": [{"status": "ok", "nuevas": 1, "actualizadas": 0}],
        "failed_months": [{"year": 2026, "month": 6, "status": "error_descarga"}],
        "steps": {"dlq_retry": "ok"},
    }

    with (
        patch("scheduler.run_update.run_bulk_pipeline", return_value=pipeline_result),
        patch("scheduler.run_update.count_licitaciones", return_value=200),
        patch("scheduler.run_update.notify") as mock_notify,
        patch("sys.argv", ["run_update"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 1
    mock_notify.assert_not_called()  # sin alerta CRITICAL "error fatal"


# ── Camino legacy de run_bulk_pipeline() (PLACSP_CONNECTOR_ENABLED=False) ────
# Ejercitan scraper.pipeline.update_recent directamente (vs. mockear
# scheduler.pipeline_runs.run_bulk_pipeline como en los tests de arriba).


class TestRunRecentBulk:
    @patch("scheduler.watchlist_alerts.check_and_notify")
    @patch("scheduler.aggregates_precompute.run_aggregates_precompute")
    @patch("scheduler.kpi_precompute.run_kpi_precompute")
    @patch("scraper.pipeline.update_recent", return_value=[{"status": "ok"}])
    def test_success(self, *mocks: MagicMock) -> None:
        from scheduler.jobs.recent_bulk import run

        run()

    @patch("scraper.pipeline.update_recent", return_value=[{"status": "error"}])
    def test_failure(self, mock_update: MagicMock) -> None:
        from scheduler.jobs.recent_bulk import run

        with pytest.raises(RuntimeError, match="bulk refresh failed"):
            run()


class TestRunRecentBulkDefault:
    @patch("scheduler.watchlist_alerts.check_and_notify")
    @patch("scheduler.aggregates_precompute.run_aggregates_precompute")
    @patch("scheduler.kpi_precompute.run_kpi_precompute")
    @patch("scraper.pipeline.update_recent", return_value=[{"status": "ok"}])
    def test_reads_env(self, mock_update: MagicMock, *mocks: MagicMock) -> None:
        with patch.dict("os.environ", {"SCHEDULER_BULK_MONTHS": "5"}):
            from scheduler.jobs.recent_bulk import run

            run()
        mock_update.assert_called_once_with(5)
