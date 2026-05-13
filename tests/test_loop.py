"""Tests para scheduler/loop.py — funciones internas del scheduler."""

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
        with patch("scheduler.loop.log"), patch("scheduler.loop.notify") as mock_notify:
            _run_job("test_job", fn)  # should not raise
        mock_notify.assert_called_once()


class TestRunDailyAtom:
    def test_ok_result_runs_downstream(self):
        from scheduler.loop import _run_daily_atom

        with (
            patch("scheduler.loop.update_daily", return_value={"status": "ok"}),
            patch("scheduler.loop.run_kpi_precompute") as mock_kpi,
            patch("scheduler.loop.check_and_notify") as mock_notify,
        ):
            _run_daily_atom()
        mock_kpi.assert_called_once()
        mock_notify.assert_called_once()

    def test_non_ok_status_raises(self):
        import pytest

        from scheduler.loop import _run_daily_atom

        with (
            patch("scheduler.loop.update_daily", return_value={"status": "error"}),
            pytest.raises(RuntimeError),
        ):
            _run_daily_atom()


class TestRunRecentBulk:
    def test_all_ok_runs_downstream(self):
        from scheduler.loop import _run_recent_bulk

        with (
            patch(
                "scheduler.loop.update_recent",
                return_value=[{"status": "ok"}, {"status": "no_publicado"}],
            ),
            patch("scheduler.loop.run_kpi_precompute") as mock_kpi,
            patch("scheduler.loop.check_and_notify") as mock_notify,
        ):
            _run_recent_bulk(2)
        mock_kpi.assert_called_once()
        mock_notify.assert_called_once()

    def test_failed_month_raises(self):
        import pytest

        from scheduler.loop import _run_recent_bulk

        with (
            patch("scheduler.loop.update_recent", return_value=[{"status": "error"}]),
            pytest.raises(RuntimeError),
        ):
            _run_recent_bulk(1)


class TestMain:
    def test_main_runs_one_iteration_then_stops(self):
        """main() ejecuta al menos una iteración antes de ser interrumpido."""
        import pytest

        from scheduler.loop import main

        call_count = {"n": 0}

        def fake_sleep(_):
            call_count["n"] += 1
            raise KeyboardInterrupt  # break the loop after first sleep

        with (
            patch("scheduler.loop.configure_logging"),
            patch("scheduler.loop._run_job"),
            patch("scheduler.loop.time") as mock_time,
            patch("scheduler.loop.log"),
        ):
            mock_time.monotonic.return_value = 0
            mock_time.sleep.side_effect = fake_sleep

            with pytest.raises(KeyboardInterrupt):
                main()

        assert call_count["n"] >= 1
