"""Tests for db/notifications.py."""

from __future__ import annotations

import pytest


@pytest.fixture()
def db(tmp_db):
    yield tmp_db[0]


# ── mark_read ─────────────────────────────────────────────────────────────────


def test_mark_read_stores_notification(db):
    from db.notifications import count_unread, get_unread_ids, mark_read

    mark_read("user1", "notif-001")
    unread = get_unread_ids("user1", ["notif-001"])
    assert unread == []
    assert count_unread("user1", ["notif-001"]) == 0


def test_mark_read_is_idempotent(db):
    from db.notifications import count_unread, mark_read

    mark_read("user1", "notif-002")
    mark_read("user1", "notif-002")  # second call must not raise
    assert count_unread("user1", ["notif-002"]) == 0


def test_mark_read_does_not_affect_other_users(db):
    from db.notifications import get_unread_ids, mark_read

    mark_read("user1", "notif-003")
    unread = get_unread_ids("user2", ["notif-003"])
    assert "notif-003" in unread


# ── mark_all_read ─────────────────────────────────────────────────────────────


def test_mark_all_read_marks_multiple(db):
    from db.notifications import count_unread, mark_all_read

    ids = ["n1", "n2", "n3"]
    mark_all_read("userA", ids)
    assert count_unread("userA", ids) == 0


def test_mark_all_read_empty_list_no_op(db):
    from db.notifications import count_unread, mark_all_read

    mark_all_read("userA", [])  # should not raise
    assert count_unread("userA", ["x"]) == 1


def test_mark_all_read_is_idempotent(db):
    from db.notifications import count_unread, mark_all_read

    ids = ["m1", "m2"]
    mark_all_read("userB", ids)
    mark_all_read("userB", ids)  # second call must not raise
    assert count_unread("userB", ids) == 0


# ── get_unread_ids ────────────────────────────────────────────────────────────


def test_get_unread_ids_returns_all_when_none_read(db):
    from db.notifications import get_unread_ids

    ids = ["a", "b", "c"]
    unread = get_unread_ids("fresh_user", ids)
    assert set(unread) == set(ids)


def test_get_unread_ids_empty_candidates(db):
    from db.notifications import get_unread_ids

    assert get_unread_ids("user1", []) == []


def test_get_unread_ids_partial_read(db):
    from db.notifications import get_unread_ids, mark_read

    mark_read("userC", "read_one")
    unread = get_unread_ids("userC", ["read_one", "unread_one"])
    assert unread == ["unread_one"]


# ── count_unread ──────────────────────────────────────────────────────────────


def test_count_unread_all_unread(db):
    from db.notifications import count_unread

    assert count_unread("new_user", ["x", "y", "z"]) == 3


def test_count_unread_all_read(db):
    from db.notifications import count_unread, mark_all_read

    ids = ["p", "q"]
    mark_all_read("userD", ids)
    assert count_unread("userD", ids) == 0


def test_count_unread_empty_list(db):
    from db.notifications import count_unread

    assert count_unread("userX", []) == 0


# ── get_last_seen_ts ──────────────────────────────────────────────────────────


def test_get_last_seen_ts_returns_none_when_no_reads(db):
    from db.notifications import get_last_seen_ts

    result = get_last_seen_ts("user_never_read")
    assert result is None


def test_get_last_seen_ts_returns_timestamp_after_read(db):
    from db.notifications import get_last_seen_ts, mark_read

    mark_read("userE", "notif-ts-001")
    ts = get_last_seen_ts("userE")
    assert ts is not None
    assert len(ts) > 0
