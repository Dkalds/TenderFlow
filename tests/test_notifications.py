"""Tests for db/notifications.py."""

from __future__ import annotations

from collections.abc import Callable

import pytest


@pytest.fixture()
def usuario(tmp_db) -> Callable[[str], int]:
    """Crea un usuario por nombre y devuelve su id: las marcas son por ``user_id``."""
    from db.users import create_user

    def _crear(nombre: str) -> int:
        return create_user(
            email=f"{nombre}@notifications.test",
            password_hash="test-hash",  # pragma: allowlist secret
            display_name=nombre,
        )

    return _crear


# ── mark_read ─────────────────────────────────────────────────────────────────


def test_mark_read_stores_notification(usuario):
    from db.notifications import get_unread_ids, mark_read

    user1 = usuario("user1")
    mark_read("notif-001", user_id=user1)
    unread = get_unread_ids(["notif-001"], user_id=user1)
    assert unread == []
    assert len(get_unread_ids(["notif-001"], user_id=user1)) == 0


def test_mark_read_is_idempotent(usuario):
    from db.notifications import get_unread_ids, mark_read

    user1 = usuario("user1")
    mark_read("notif-002", user_id=user1)
    mark_read("notif-002", user_id=user1)  # second call must not raise
    assert len(get_unread_ids(["notif-002"], user_id=user1)) == 0


def test_mark_read_does_not_affect_other_users(usuario):
    from db.notifications import get_unread_ids, mark_read

    mark_read("notif-003", user_id=usuario("user1"))
    unread = get_unread_ids(["notif-003"], user_id=usuario("user2"))
    assert "notif-003" in unread


# ── mark_all_read ─────────────────────────────────────────────────────────────


def test_mark_all_read_marks_multiple(usuario):
    from db.notifications import get_unread_ids, mark_all_read

    user_a = usuario("userA")
    ids = ["n1", "n2", "n3"]
    mark_all_read(ids, user_id=user_a)
    assert len(get_unread_ids(ids, user_id=user_a)) == 0


def test_mark_all_read_empty_list_no_op(usuario):
    from db.notifications import get_unread_ids, mark_all_read

    user_a = usuario("userA")
    mark_all_read([], user_id=user_a)  # should not raise
    assert len(get_unread_ids(["x"], user_id=user_a)) == 1


def test_mark_all_read_is_idempotent(usuario):
    from db.notifications import get_unread_ids, mark_all_read

    user_b = usuario("userB")
    ids = ["m1", "m2"]
    mark_all_read(ids, user_id=user_b)
    mark_all_read(ids, user_id=user_b)  # second call must not raise
    assert len(get_unread_ids(ids, user_id=user_b)) == 0


# ── get_unread_ids ────────────────────────────────────────────────────────────


def test_get_unread_ids_returns_all_when_none_read(usuario):
    from db.notifications import get_unread_ids

    ids = ["a", "b", "c"]
    unread = get_unread_ids(ids, user_id=usuario("fresh_user"))
    assert set(unread) == set(ids)


def test_get_unread_ids_empty_candidates(usuario):
    from db.notifications import get_unread_ids

    assert get_unread_ids([], user_id=usuario("user1")) == []


def test_get_unread_ids_partial_read(usuario):
    from db.notifications import get_unread_ids, mark_read

    user_c = usuario("userC")
    mark_read("read_one", user_id=user_c)
    unread = get_unread_ids(["read_one", "unread_one"], user_id=user_c)
    assert unread == ["unread_one"]


# ── no leídas (len de get_unread_ids) ──────────────────────────────────────────────────────────────


def test_count_unread_all_unread(usuario):
    from db.notifications import get_unread_ids

    assert len(get_unread_ids(["x", "y", "z"], user_id=usuario("new_user"))) == 3


def test_count_unread_all_read(usuario):
    from db.notifications import get_unread_ids, mark_all_read

    user_d = usuario("userD")
    ids = ["p", "q"]
    mark_all_read(ids, user_id=user_d)
    assert len(get_unread_ids(ids, user_id=user_d)) == 0


def test_count_unread_empty_list(usuario):
    from db.notifications import get_unread_ids

    assert len(get_unread_ids([], user_id=usuario("userX"))) == 0


# ── get_last_seen_ts ──────────────────────────────────────────────────────────


def test_get_last_seen_ts_returns_none_when_no_reads(usuario):
    from db.notifications import get_last_seen_ts

    result = get_last_seen_ts(user_id=usuario("user_never_read"))
    assert result is None


def test_get_last_seen_ts_returns_timestamp_after_read(usuario):
    from db.notifications import get_last_seen_ts, mark_read

    user_e = usuario("userE")
    mark_read("notif-ts-001", user_id=user_e)
    ts = get_last_seen_ts(user_id=user_e)
    assert ts is not None
    assert len(ts) > 0
