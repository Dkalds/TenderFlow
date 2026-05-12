"""Tests para acciones operativas de DLQ."""

from __future__ import annotations

from unittest.mock import patch


def test_retry_bulk_failure_resolves_on_ok(tmp_db):
    from db import dlq
    from scheduler.dlq_actions import retry_failure

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("x"), scope="download")
    failure_id = dlq.list_unresolved()[0]["id"]

    with (
        patch("scheduler.dlq_actions.bind_run_context", return_value="retry-run"),
        patch(
            "scheduler.dlq_actions.process_month",
            return_value={"status": "ok", "year": 2026, "month": 1},
        ) as process_month,
    ):
        result = retry_failure(failure_id)

    process_month.assert_called_once_with(2026, 1, run_id="retry-run", force=True)
    assert result["status"] == "resolved"
    assert dlq.list_unresolved() == []


def test_retry_bulk_failure_increments_retry_on_failure(tmp_db):
    from db import dlq
    from scheduler.dlq_actions import retry_failure

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("x"), scope="download")
    failure_id = dlq.list_unresolved()[0]["id"]

    with (
        patch("scheduler.dlq_actions.bind_run_context", return_value="retry-run"),
        patch(
            "scheduler.dlq_actions.process_month",
            return_value={"status": "error_descarga"},
        ),
    ):
        result = retry_failure(failure_id)

    assert result["status"] == "failed"
    assert dlq.list_unresolved()[0]["retry_count"] == 1


def test_retry_unknown_source_raises(tmp_db):
    import pytest

    from db import dlq
    from scheduler.dlq_actions import retry_failure

    dlq.record_failure("run-1", "custom", RuntimeError("x"))
    failure_id = dlq.list_unresolved()[0]["id"]

    with (
        patch("scheduler.dlq_actions.bind_run_context", return_value="retry-run"),
        pytest.raises(ValueError, match="Unsupported"),
    ):
        retry_failure(failure_id)
