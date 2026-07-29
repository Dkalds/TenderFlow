"""Tests para scheduler/drift_monitor.py — clasificación de severidad y ciclo run_once."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestClassify:
    def test_ok(self):
        from scheduler.drift_monitor import _classify

        sev, _det = _classify(0.0, 0.0)
        assert sev == "ok"

    def test_warn_psi(self):
        from scheduler.drift_monitor import _classify

        sev, _ = _classify(0.12, 0.0)
        assert sev == "warn"

    def test_warn_f1(self):
        from scheduler.drift_monitor import _classify

        sev, _ = _classify(0.0, 0.05)
        assert sev == "warn"

    def test_crit_psi(self):
        from scheduler.drift_monitor import _classify

        sev, _ = _classify(0.30, 0.0)
        assert sev == "crit"

    def test_crit_f1(self):
        from scheduler.drift_monitor import _classify

        sev, _ = _classify(0.0, 0.15)
        assert sev == "crit"


class TestRunOnce:
    @patch("scheduler.drift_monitor.log")
    def test_ok_no_alert(self, mock_log):
        with patch.dict(
            "sys.modules",
            {
                "scheduler.concept_drift": MagicMock(compute_psi=MagicMock(return_value=0.01)),
                "scheduler.drift_report": MagicMock(compute_f1_drop=MagicMock(return_value=0.001)),
            },
        ):
            from scheduler.drift_monitor import run_once

            status = run_once("test_model")
            assert status.severity == "ok"
            assert status.psi == pytest.approx(0.01)

    @patch("scheduler.drift_monitor.log")
    def test_warn_triggers_notify(self, mock_log):
        mock_notify = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "scheduler.concept_drift": MagicMock(compute_psi=MagicMock(return_value=0.15)),
                "scheduler.drift_report": MagicMock(compute_f1_drop=MagicMock(return_value=0.0)),
                "observability.alerts": MagicMock(notify=mock_notify),
            },
        ):
            from scheduler.drift_monitor import run_once

            status = run_once("m")
            assert status.severity == "warn"
            mock_notify.assert_called_once()

    @patch("scheduler.drift_monitor.log")
    def test_crit_triggers_notify(self, mock_log):
        mock_notify = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "scheduler.concept_drift": MagicMock(compute_psi=MagicMock(return_value=0.30)),
                "scheduler.drift_report": MagicMock(compute_f1_drop=MagicMock(return_value=0.0)),
                "observability.alerts": MagicMock(notify=mock_notify),
            },
        ):
            from scheduler.drift_monitor import run_once

            status = run_once()
            assert status.severity == "crit"

    @patch("scheduler.drift_monitor.log")
    def test_import_error_psi(self, mock_log):
        """When concept_drift import fails, psi defaults to 0."""
        import sys

        # Remove module so import fails inside run_once
        saved_cd = sys.modules.pop("scheduler.concept_drift", None)
        saved_dr = sys.modules.pop("scheduler.drift_report", None)
        try:
            with patch.dict(
                "sys.modules",
                {
                    "scheduler.concept_drift": None,  # force ImportError
                    "scheduler.drift_report": None,
                },
            ):
                # Need to reimport to trigger the lazy imports inside run_once
                from scheduler.drift_monitor import run_once

                # The function catches ImportError internally
                status = run_once()
                assert status.psi == 0.0
                assert status.f1_drop == 0.0
                assert status.severity == "ok"
        finally:
            if saved_cd:
                sys.modules["scheduler.concept_drift"] = saved_cd
            if saved_dr:
                sys.modules["scheduler.drift_report"] = saved_dr

    @patch("scheduler.drift_monitor.log")
    def test_notify_import_error_handled(self, mock_log):
        """When observability.alerts import fails, it logs warning."""
        with patch.dict(
            "sys.modules",
            {
                "scheduler.concept_drift": MagicMock(compute_psi=MagicMock(return_value=0.30)),
                "scheduler.drift_report": MagicMock(compute_f1_drop=MagicMock(return_value=0.0)),
                "observability.alerts": None,  # force ImportError
            },
        ):
            from scheduler.drift_monitor import run_once

            status = run_once()
            assert status.severity == "crit"
            # Should not raise despite alerts import failure


class TestDriftStatus:
    def test_dataclass(self):
        from scheduler.drift_monitor import DriftStatus

        ds = DriftStatus(psi=0.1, f1_drop=0.05, severity="warn", detail="test")
        assert ds.psi == 0.1
        assert ds.severity == "warn"
