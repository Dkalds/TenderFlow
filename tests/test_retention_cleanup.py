"""Tests para scheduler/jobs/retention_cleanup.py — job wrapper de scheduler/retention.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestRunRetentionCleanup:
    @patch("scheduler.retention.run_retention", return_value={"deleted": 10})
    def test_calls_retention(self, mock_retention: MagicMock) -> None:
        from scheduler.jobs.retention_cleanup import run

        result = run()
        assert result == {"deleted": 10}
        mock_retention.assert_called_once()
