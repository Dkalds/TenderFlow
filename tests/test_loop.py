"""Tests para scheduler/loop.py y scheduler/jobs/ — funciones internas del scheduler."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


class TestEnvInt:
    def test_returns_default_when_not_set(self):
        from scheduler.loop import _env_int

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TEST_VAR_XYZ", None)
            assert _env_int("TEST_VAR_XYZ", 42) == 42

    def test_returns_env_value(self):
        from scheduler.loop import _env_int

        with patch.dict(os.environ, {"TEST_VAR_XYZ": "10"}):
            assert _env_int("TEST_VAR_XYZ", 42) == 10

    def test_invalid_value_returns_default(self):
        from scheduler.loop import _env_int

        with patch.dict(os.environ, {"TEST_VAR_XYZ": "not_a_number"}):
            assert _env_int("TEST_VAR_XYZ", 42) == 42

    def test_enforces_min_value(self):
        from scheduler.loop import _env_int

        with patch.dict(os.environ, {"TEST_VAR_XYZ": "0"}):
            assert _env_int("TEST_VAR_XYZ", 5, min_value=1) == 1

    def test_negative_clamped_to_min(self):
        from scheduler.loop import _env_int

        with patch.dict(os.environ, {"TEST_VAR_XYZ": "-5"}):
            assert _env_int("TEST_VAR_XYZ", 10, min_value=1) == 1


class TestRunJob:
    def test_calls_function_and_logs(self):
        from scheduler.loop import _run_job

        fn = MagicMock(return_value={"status": "ok"})
        with patch("scheduler.loop.log") as mock_log:
            _run_job("test_job", fn)
        fn.assert_called_once()
        mock_log.info.assert_called_once()

    def test_exception_is_caught_and_notified(self):
        from scheduler.loop import _run_job

        fn = MagicMock(side_effect=RuntimeError("boom"))
        with patch("scheduler.loop.log") as mock_log, patch("scheduler.loop.notify") as mock_notify:
            _run_job("test_job", fn)  # should not raise
        mock_notify.assert_called_once()
        mock_log.error.assert_called_once()
        assert mock_log.error.call_args.kwargs["exc_info"][1].args == ("boom",)

    def test_heavy_flag_delegates_to_run_heavy_job(self):
        from scheduler.loop import _run_job

        fn = MagicMock()
        with (
            patch("scheduler.loop._run_heavy_job", return_value=True) as mock_heavy,
            patch("scheduler.loop.log"),
        ):
            result = _run_job("test_heavy", fn, heavy=True)
        mock_heavy.assert_called_once_with("test_heavy", fn)
        assert result is True


class TestBackoff:
    def test_no_failures_returns_base(self):
        from scheduler.loop import _backoff_interval, _consecutive_failures

        _consecutive_failures.pop("test_job", None)
        from datetime import timedelta

        base = timedelta(minutes=60)
        assert _backoff_interval("test_job", base) == base

    def test_one_failure_doubles(self):
        from datetime import timedelta

        from scheduler.loop import _backoff_interval, _consecutive_failures

        _consecutive_failures["test_backoff"] = 1
        base = timedelta(minutes=60)
        with patch("scheduler.loop.log"):
            result = _backoff_interval("test_backoff", base)
        assert result == timedelta(minutes=120)
        _consecutive_failures.pop("test_backoff", None)

    def test_max_backoff_capped(self):
        from datetime import timedelta

        from scheduler.loop import _backoff_interval, _consecutive_failures

        _consecutive_failures["test_cap"] = 100
        base = timedelta(minutes=60)
        with patch("scheduler.loop.log"):
            result = _backoff_interval("test_cap", base)
        # MAX_BACKOFF_MULTIPLIER = 8
        assert result == timedelta(minutes=480)
        _consecutive_failures.pop("test_cap", None)


class TestJobRegistry:
    def test_build_default_registry_returns_all_jobs(self):
        from scheduler.jobs import build_default_registry

        registry = build_default_registry()
        names = [j.name for j in registry]
        assert "daily_atom" in names
        assert "recent_bulk" in names
        assert "retention_cleanup" in names
        assert "faiss_rebuild" not in names
        assert "dlq_retry" in names
        assert "digest_daily" in names
        assert "anomaly_checks" in names
        assert "drift_report" in names
        assert "wal_checkpoint" in names
        assert "ml_scoring_baja" in names
        assert "ml_retrain_baja" in names
        assert "documentos_embeddings" in names
        assert "watchlist_rules" in names
        assert len(registry) == 12

    def test_heavy_jobs_marked_correctly(self):
        from scheduler.jobs import build_default_registry

        registry = build_default_registry()
        heavy_names = {j.name for j in registry if j.heavy}
        assert heavy_names == {
            "daily_atom",
            "recent_bulk",
            "retention_cleanup",
            "ml_scoring_baja",
            "ml_retrain_baja",
            "documentos_embeddings",
        }

    def test_all_jobs_have_callable_fn(self):
        from scheduler.jobs import build_default_registry

        for job in build_default_registry():
            assert callable(job.fn), f"{job.name}.fn is not callable"

    def test_all_jobs_have_unique_names(self):
        from scheduler.jobs import build_default_registry

        registry = build_default_registry()
        names = [j.name for j in registry]
        assert len(names) == len(set(names)), "Duplicate job names found"

    def test_scheduled_job_dataclass(self):
        from scheduler.jobs._base import ScheduledJob

        job = ScheduledJob(
            name="test",
            fn=lambda: None,
            interval_env="TEST_INTERVAL",
            default_interval_minutes=60,
            initial_offset_minutes=5,
            heavy=True,
        )
        assert job.name == "test"
        assert job.heavy is True
        assert job.initial_offset_minutes == 5


class TestResolveInterval:
    def test_minutes_env_var(self):
        from scheduler.jobs._base import ScheduledJob
        from scheduler.loop import _resolve_interval

        job = ScheduledJob(
            name="test",
            fn=lambda: None,
            interval_env="TEST_INTERVAL_MINUTES",
            default_interval_minutes=120,
        )
        with patch.dict(os.environ, {"TEST_INTERVAL_MINUTES": "30"}):
            from datetime import timedelta

            assert _resolve_interval(job) == timedelta(minutes=30)

    def test_hours_env_var(self):
        from scheduler.jobs._base import ScheduledJob
        from scheduler.loop import _resolve_interval

        job = ScheduledJob(
            name="test",
            fn=lambda: None,
            interval_env="TEST_INTERVAL_HOURS",
            default_interval_minutes=360,
        )
        with patch.dict(os.environ, {"TEST_INTERVAL_HOURS": "2"}):
            from datetime import timedelta

            assert _resolve_interval(job) == timedelta(hours=2)

    def test_default_when_env_missing(self):
        from scheduler.jobs._base import ScheduledJob
        from scheduler.loop import _resolve_interval

        job = ScheduledJob(
            name="test",
            fn=lambda: None,
            interval_env="NONEXISTENT_ENV_VAR_MINUTES",
            default_interval_minutes=90,
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NONEXISTENT_ENV_VAR_MINUTES", None)
            from datetime import timedelta

            assert _resolve_interval(job) == timedelta(minutes=90)


class TestMain:
    def test_main_runs_one_iteration_then_stops(self):
        """main() ejecuta al menos una iteración antes de ser interrumpido."""
        from scheduler.loop import _stop_event, main

        call_count = {"n": 0}

        original_wait = _stop_event.wait

        def fake_wait(timeout=None):
            call_count["n"] += 1
            return True  # simula señal de parada → salida limpia del bucle

        with (
            patch("scheduler.loop.configure_logging"),
            patch("scheduler.loop._run_job"),
            patch("scheduler.loop.log"),
        ):
            _stop_event.wait = fake_wait
            try:
                result = main()
            finally:
                _stop_event.wait = original_wait
                _stop_event.clear()

        assert call_count["n"] >= 1
        assert result == 0
