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
        with (
            patch("scheduler.run_update.run_daily_pipeline") as mock_pipeline,
            patch("scheduler.run_update.count_licitaciones", return_value=0),
        ):
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
        with (
            patch("scheduler.run_update.run_bulk_pipeline") as mock_pipeline,
            patch("scheduler.run_update.count_licitaciones", return_value=0),
        ):
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
            "scheduler.pipeline_runs._run_tech_signal_merge": _make_mock("tech_signal_merge"),
            "scheduler.pipeline_runs._run_kpi_precompute": _make_mock("kpi_precompute"),
            "scheduler.pipeline_runs._run_aggregates_precompute": _make_mock(
                "aggregates_precompute"
            ),
            "scheduler.pipeline_runs._run_watchlist_notify": _make_mock("watchlist_notify"),
            "scheduler.pipeline_runs._run_digests": _make_mock("digests"),
            "scheduler.pipeline_runs._run_dlq_retry": _make_mock("dlq_retry"),
            "scheduler.pipeline_runs._run_anomaly_checks": _make_mock("anomaly_checks"),
            "scheduler.pipeline_runs._run_retention_cleanup": _make_mock("retention_cleanup"),
            "scheduler.pipeline_runs._run_ml_retrain": _make_mock("ml_retrain"),
            "scheduler.pipeline_runs._run_sap_active_learning": _make_mock("sap_active_learning"),
            "scheduler.pipeline_runs._run_drift_checks": _make_mock("drift_checks"),
        }

        with patch.multiple(
            "scheduler.pipeline_runs", **{k.split(".")[-1]: v for k, v in patches.items()}
        ):
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
            patch("scheduler.pipeline_runs._run_tech_signal_merge"),
            patch("scheduler.pipeline_runs._run_kpi_precompute"),
            patch("scheduler.pipeline_runs._run_aggregates_precompute"),
            patch("scheduler.pipeline_runs._run_watchlist_notify"),
            patch("scheduler.pipeline_runs._run_digests"),
            patch("scheduler.pipeline_runs._run_dlq_retry"),
            patch("scheduler.pipeline_runs._run_anomaly_checks"),
            patch("scheduler.pipeline_runs._run_retention_cleanup"),
            patch("scheduler.pipeline_runs._run_ml_retrain"),
            patch("scheduler.pipeline_runs._run_drift_checks"),
        ):
            results = _run_post_ingestion_steps()

        assert results["ml_scoring"] == "error"
        # All other steps still ran
        assert results["kpi_precompute"] == "ok"
        assert results["aggregates_precompute"] == "ok"


class TestLaneAwareSteps:
    """El carril diario y el bulk no hacen el mismo trabajo en cada paso.

    Reintentar una entrada DLQ ``bulk_YYYYMM`` es reprocesar el mes entero.
    Hacerlo dentro del carril diario se comía su timeout y GitHub cancelaba el
    job a mitad de la cadena post-ingesta (runs de 2026-08-01/03).
    """

    def test_daily_lane_skips_bulk_months_in_dlq(self) -> None:
        from scheduler.pipeline_runs import LANE_DAILY, _run_dlq_retry

        with patch("scheduler.dlq_retry.retry_failed_extractions") as retry:
            _run_dlq_retry(lane=LANE_DAILY)

        retry.assert_called_once_with(include_bulk=False)

    def test_bulk_lane_retries_bulk_months(self) -> None:
        from scheduler.pipeline_runs import LANE_BULK, _run_dlq_retry

        with patch("scheduler.dlq_retry.retry_failed_extractions") as retry:
            _run_dlq_retry(lane=LANE_BULK)

        retry.assert_called_once_with(include_bulk=True)

    def test_default_lane_is_the_permissive_one(self) -> None:
        """Un caller que no declare carril no pierde trabajo en silencio."""
        from scheduler.pipeline_runs import _run_dlq_retry

        with patch("scheduler.dlq_retry.retry_failed_extractions") as retry:
            _run_dlq_retry()

        retry.assert_called_once_with(include_bulk=True)

    def test_post_ingestion_forwards_lane_only_to_lane_aware_steps(self) -> None:
        """``lane`` llega a dlq_retry y a nadie más: el resto no lo acepta."""
        from scheduler.pipeline_runs import LANE_DAILY, _run_post_ingestion_steps

        with (
            patch("scheduler.pipeline_runs._run_ml_scoring") as ml_scoring,
            patch("scheduler.pipeline_runs._run_ml_tecnologias"),
            patch("scheduler.pipeline_runs._run_tech_signal_merge"),
            patch("scheduler.pipeline_runs._run_kpi_precompute"),
            patch("scheduler.pipeline_runs._run_aggregates_precompute"),
            patch("scheduler.pipeline_runs._run_watchlist_notify"),
            patch("scheduler.pipeline_runs._run_digests"),
            patch("scheduler.pipeline_runs._run_dlq_retry") as dlq_retry,
            patch("scheduler.pipeline_runs._run_anomaly_checks"),
            patch("scheduler.pipeline_runs._run_retention_cleanup"),
            patch("scheduler.pipeline_runs._run_ml_retrain"),
            patch("scheduler.pipeline_runs._run_sap_active_learning"),
            patch("scheduler.pipeline_runs._run_drift_checks"),
        ):
            results = _run_post_ingestion_steps(lane=LANE_DAILY)

        dlq_retry.assert_called_once_with(lane=LANE_DAILY)
        ml_scoring.assert_called_once_with()
        assert results["dlq_retry"] == "ok"

    def test_lane_aware_steps_all_have_an_implementation(self) -> None:
        """Si un paso sale de CANONICAL_STEPS, no puede quedar en la frozenset."""
        from scheduler.pipeline_runs import _LANE_AWARE_STEPS, CANONICAL_STEPS

        assert set(CANONICAL_STEPS) >= _LANE_AWARE_STEPS
