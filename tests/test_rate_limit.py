"""Tests para db.rate_limits."""

from __future__ import annotations


def test_db_rate_limit_cleanup_expired(tmp_db):
    from db.rate_limits import cleanup_expired

    result = cleanup_expired(window_seconds=0)
    assert isinstance(result, int)


def test_db_is_login_locked_out_not_locked(tmp_db):
    from db.rate_limits import is_login_locked_out

    locked, remaining = is_login_locked_out("test_client", max_attempts=5)
    assert locked is False
    assert remaining == 0.0


def test_db_record_failed_login_increments(tmp_db):
    from db.rate_limits import record_failed_login

    c1 = record_failed_login("client_x")
    c2 = record_failed_login("client_x")
    assert c2 == c1 + 1


def test_db_clear_login_attempts_works(tmp_db):
    from db.rate_limits import clear_login_attempts, record_failed_login

    record_failed_login("client_y")
    clear_login_attempts("client_y")


def test_db_rate_limit_fail_open_on_bad_key(tmp_db):
    from unittest.mock import patch

    from db.rate_limits import check_rate_limit_db

    with patch("db.rate_limits._connect", side_effect=RuntimeError("db error")):
        result = check_rate_limit_db("test_key", max_calls=5)
    assert result is False
