"""Tests para scheduler/dlq_retry.py — backoff y reintento DLQ."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

# ---------------------------------------------------------------------------
# _backoff_seconds
# ---------------------------------------------------------------------------


def test_backoff_seconds_base():
    from scheduler.dlq_retry import _BASE_BACKOFF_S, _backoff_seconds

    assert _backoff_seconds(0) == float(_BASE_BACKOFF_S)


def test_backoff_seconds_doubles_each_retry():
    from scheduler.dlq_retry import _BASE_BACKOFF_S, _backoff_seconds

    assert _backoff_seconds(1) == float(_BASE_BACKOFF_S * 2)
    assert _backoff_seconds(2) == float(_BASE_BACKOFF_S * 4)


def test_backoff_seconds_caps_at_max():
    from scheduler.dlq_retry import _MAX_BACKOFF_S, _backoff_seconds

    assert _backoff_seconds(20) == float(_MAX_BACKOFF_S)


# ---------------------------------------------------------------------------
# _is_due
# ---------------------------------------------------------------------------


def test_is_due_missing_created_at():
    from scheduler.dlq_retry import _is_due

    assert _is_due({"retry_count": 0}) is True


def test_is_due_invalid_date():
    from scheduler.dlq_retry import _is_due

    assert _is_due({"created_at": "not-a-date", "retry_count": 0}) is True


def test_is_due_recent_failure_not_due():
    from scheduler.dlq_retry import _is_due

    now_str = datetime.now(UTC).isoformat()
    assert _is_due({"created_at": now_str, "retry_count": 0}) is False


def test_is_due_old_failure_is_due():
    from scheduler.dlq_retry import _is_due

    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    assert _is_due({"created_at": old, "retry_count": 0}) is True


def test_is_due_naive_datetime_treated_as_utc():
    from scheduler.dlq_retry import _is_due

    old = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    assert _is_due({"created_at": old, "retry_count": 0}) is True


# ---------------------------------------------------------------------------
# retry_failed_extractions — happy paths and edge cases
# ---------------------------------------------------------------------------


def test_retry_empty_queue(tmp_db):
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions()
    assert result == 0


def test_retry_all_in_backoff(tmp_db):
    """Fallo reciente (backoff no expirado) no se reintenta."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    # created_at = ahora → backoff de 300s no ha expirado
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions()
    assert result == 0


def test_retry_max_retries_skipped(tmp_db, monkeypatch):
    """Entradas con retry_count >= max_retries se filtran antes de intentar."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    fid = dlq.list_unresolved()[0]["id"]
    for _ in range(5):
        dlq.increment_retry(fid)
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions(max_retries=5)
    assert result == 0


def test_retry_unknown_source_increments_retry(tmp_db, monkeypatch):
    """Fuente desconocida → no resuelto, retry_count incrementado."""
    from db import dlq

    dlq.record_failure("run-1", "unknown_source_xyz", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions()
    assert result == 0
    items = dlq.list_unresolved()
    assert items[0]["retry_count"] == 1


def test_retry_bulk_success(tmp_db, monkeypatch):
    """Reintento bulk exitoso → marcado como resuelto."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch("scraper.pipeline.process_month", return_value={"status": "ok"}):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 1
    assert dlq.list_unresolved() == []


def test_retry_bulk_failure_increments_retry(tmp_db, monkeypatch):
    """Reintento bulk fallido → no resuelto, retry_count incrementado."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch("scraper.pipeline.process_month", return_value={"status": "error"}):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 0
    assert dlq.list_unresolved()[0]["retry_count"] == 1


def test_retry_bulk_bad_format(tmp_db, monkeypatch):
    """Fuente bulk_ con formato inesperado → no resuelto."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_BADVAL", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    from scheduler.dlq_retry import retry_failed_extractions

    result = retry_failed_extractions()
    assert result == 0


def test_retry_atom_success(tmp_db, monkeypatch):
    """Reintento place_live_atom exitoso → resuelto."""
    from db import dlq

    dlq.record_failure("run-1", "place_live_atom", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch("scraper.pipeline.process_daily", return_value={"status": "ok"}):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 1
    assert dlq.list_unresolved() == []


def test_retry_atom_failure(tmp_db, monkeypatch):
    """Reintento atom fallido → no resuelto."""
    from db import dlq

    dlq.record_failure("run-1", "atom_live", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch("scraper.pipeline.process_daily", return_value={"status": "timeout"}):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 0


def test_retry_exception_in_scraper(tmp_db, monkeypatch):
    """Excepción inesperada en el scraper → no resuelto, sin crash."""
    from db import dlq

    dlq.record_failure("run-1", "bulk_202601", RuntimeError("err"))
    monkeypatch.setattr("scheduler.dlq_retry._is_due", lambda f: True)
    with patch("scraper.pipeline.process_month", side_effect=RuntimeError("scraper crash")):
        from scheduler.dlq_retry import retry_failed_extractions

        result = retry_failed_extractions()
    assert result == 0
