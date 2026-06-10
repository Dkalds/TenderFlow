"""Tests de paridad de pipeline canónica (ADR-012).

Verifica que ``run_update --daily``, ``run_update --months``, ``daily_atom``
y ``recent_bulk`` invocan exactamente la misma secuencia de pasos canónica
definida en ``scheduler.pipeline_runs``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestDailyPipelineParity:
    """run_update --daily y daily_atom invocan la misma secuencia canónica."""

    def test_run_update_daily_delegates_to_canonical(self) -> None:
        """run_update --daily calls run_daily_pipeline from pipeline_runs."""
        with patch("scheduler.run_update.run_daily_pipeline") as mock_pipeline:
            mock_pipeline.return_value = {
                "status": "ok",
                "ingestion_result": {"status": "ok", "inserted": [], "modified": []},
                "steps": {},
            }
            from scheduler.run_update import main

            with patch("sys.argv", ["run_update", "--daily"]):
                result = main()

            mock_pipeline.assert_called_once()
            assert result == 0

    def test_daily_atom_delegates_to_canonical(self) -> None:
        """scheduler/jobs/daily_atom.run() calls run_daily_pipeline."""
        with patch("scheduler.pipeline_runs.run_daily_pipeline") as mock_pipeline:
            mock_pipeline.return_value = {
                "status": "ok",
                "ingestion_result": {"status": "ok", "inserted": [], "modified": []},
                "steps": {},
            }
            from scheduler.jobs.daily_atom import run

            run()
            mock_pipeline.assert_called_once()


class TestBulkPipelineParity:
    """run_update --months y recent_bulk invocan la misma secuencia canónica."""

    def test_run_update_bulk_delegates_to_canonical(self) -> None:
        """run_update --months calls run_bulk_pipeline from pipeline_runs."""
        with patch("scheduler.run_update.run_bulk_pipeline") as mock_pipeline:
            mock_pipeline.return_value = {
                "status": "ok",
                "ingestion_results": [{"status": "ok", "nuevas": 5, "actualizadas": 2}],
                "steps": {},
            }
            from scheduler.run_update import main

            with patch("sys.argv", ["run_update", "--months", "3"]):
                result = main()

            mock_pipeline.assert_called_once_with(3)
            assert result == 0

    def test_recent_bulk_delegates_to_canonical(self) -> None:
        """scheduler/jobs/recent_bulk.run() calls run_bulk_pipeline."""
        with patch("scheduler.pipeline_runs.run_bulk_pipeline") as mock_pipeline:
            mock_pipeline.return_value = {
                "status": "ok",
                "ingestion_results": [],
                "steps": {},
            }
            from scheduler.jobs.recent_bulk import run

            with patch.dict("os.environ", {"SCHEDULER_BULK_MONTHS": "3"}):
                run()

            mock_pipeline.assert_called_once_with(3)


class TestCanonicalPipelineSteps:
    """La pipeline canónica ejecuta todos los pasos en el orden correcto."""

    def test_post_ingestion_steps_order(self) -> None:
        """_run_post_ingestion_steps calls all steps in the canonical order."""
        from scheduler.pipeline_runs import CANONICAL_STEPS, _run_post_ingestion_steps

        called: list[str] = []

        def _make_mock(name: str) -> MagicMock:
            def side_effect(*args: object, **kwargs: object) -> None:
                called.append(name)

            m = MagicMock(side_effect=side_effect)
            return m

        patches = {
            "scheduler.pipeline_runs._run_ml_scoring": _make_mock("ml_scoring"),
            "scheduler.pipeline_runs._run_ml_tecnologias": _make_mock("ml_tecnologias"),
            "scheduler.pipeline_runs._run_analytics_export": _make_mock("analytics_export"),
            "scheduler.pipeline_runs._run_kpi_precompute": _make_mock("kpi_precompute"),
            "scheduler.pipeline_runs._run_aggregates_precompute": _make_mock(
                "aggregates_precompute"
            ),
            "scheduler.pipeline_runs._run_watchlist_notify": _make_mock("watchlist_notify"),
            "scheduler.pipeline_runs._run_dlq_retry": _make_mock("dlq_retry"),
            "scheduler.pipeline_runs._run_anomaly_checks": _make_mock("anomaly_checks"),
        }

        with patch.multiple("scheduler.pipeline_runs", **{k.split(".")[-1]: v for k, v in patches.items()}):
            results = _run_post_ingestion_steps()

        assert called == CANONICAL_STEPS
        assert all(v == "ok" for v in results.values())

    def test_post_ingestion_step_failure_continues(self) -> None:
        """A failing step is recorded as 'error' but does not stop other steps."""
        from scheduler.pipeline_runs import _run_post_ingestion_steps

        def _boom() -> None:
            raise RuntimeError("boom")

        with (
            patch("scheduler.pipeline_runs._run_ml_scoring", side_effect=_boom),
            patch("scheduler.pipeline_runs._run_ml_tecnologias"),
            patch("scheduler.pipeline_runs._run_analytics_export"),
            patch("scheduler.pipeline_runs._run_kpi_precompute"),
            patch("scheduler.pipeline_runs._run_aggregates_precompute"),
            patch("scheduler.pipeline_runs._run_watchlist_notify"),
            patch("scheduler.pipeline_runs._run_dlq_retry"),
            patch("scheduler.pipeline_runs._run_anomaly_checks"),
        ):
            results = _run_post_ingestion_steps()

        assert results["ml_scoring"] == "error"
        # All other steps still ran
        assert results["kpi_precompute"] == "ok"
        assert results["aggregates_precompute"] == "ok"
