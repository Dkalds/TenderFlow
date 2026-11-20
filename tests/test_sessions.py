"""Tests for db/sessions.py."""

from __future__ import annotations

import db.sessions as smod

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_session(db_mod: object, user_id: int = 1, ttl_hours: int = 168) -> str:
    """Create a session via monkeypatched DB and return the raw token."""
    return smod.create_session(
        user_id, ip="127.0.0.1", user_agent="test-agent", ttl_hours=ttl_hours
    )


# ---------------------------------------------------------------------------
# _hash_token
# ---------------------------------------------------------------------------


def test_hash_token_is_hex(tmp_db: object) -> None:
    import db.sessions as s

    h = s._hash_token("hello")
    assert len(h) == 64
    int(h, 16)  # raises ValueError if not valid hex


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


def test_create_session_returns_string(tmp_db: object) -> None:
    token = _make_session(tmp_db)
    assert isinstance(token, str)
    assert len(token) > 20


def test_create_session_different_tokens(tmp_db: object) -> None:
    t1 = _make_session(tmp_db, user_id=1)
    t2 = _make_session(tmp_db, user_id=1)
    assert t1 != t2


def _activa(token: str, user_id: int) -> bool:
    """La sesión sigue entre las activas de su usuario (sin revocar ni caducar)."""
    token_hash = smod._hash_token(token)
    return any(s["token_hash"] == token_hash for s in smod.list_active_sessions(user_id))


# ---------------------------------------------------------------------------
# revoke_session
# ---------------------------------------------------------------------------


def test_revoke_session_idempotent(tmp_db: object) -> None:
    token = _make_session(tmp_db)
    smod.revoke_session(token)
    smod.revoke_session(token)  # second call should not raise
    assert not _activa(token, 1)


def test_revoke_nonexistent_session_no_error(tmp_db: object) -> None:
    smod.revoke_session("nonexistent-token-xyz")  # should not raise


# ---------------------------------------------------------------------------
# revoke_all_sessions
# ---------------------------------------------------------------------------


def test_revoke_all_sessions_returns_count(tmp_db: object) -> None:
    _make_session(tmp_db, user_id=99)
    _make_session(tmp_db, user_id=99)
    n = smod.revoke_all_sessions(99)
    assert n >= 2


def test_revoke_all_sessions_revokes_all(tmp_db: object) -> None:
    t1 = _make_session(tmp_db, user_id=88)
    t2 = _make_session(tmp_db, user_id=88)
    smod.revoke_all_sessions(88)
    assert not _activa(t1, 88)
    assert not _activa(t2, 88)


def test_revoke_all_sessions_no_cross_user(tmp_db: object) -> None:
    t_other = _make_session(tmp_db, user_id=77)
    smod.revoke_all_sessions(55)  # different user
    assert _activa(t_other, 77)


# ---------------------------------------------------------------------------
# purge_expired_sessions
# ---------------------------------------------------------------------------


def test_purge_expired_sessions_returns_int(tmp_db: object) -> None:
    _make_session(tmp_db, ttl_hours=-1)
    result = smod.purge_expired_sessions()
    assert isinstance(result, int)


# ---------------------------------------------------------------------------
# list_active_sessions
# ---------------------------------------------------------------------------


def test_list_active_sessions_returns_active(tmp_db: object) -> None:
    _make_session(tmp_db, user_id=11)
    sessions = smod.list_active_sessions(11)
    assert len(sessions) >= 1
    assert "token_hash" in sessions[0]


def test_list_active_sessions_excludes_revoked(tmp_db: object) -> None:
    token = _make_session(tmp_db, user_id=22)
    smod.revoke_session(token)
    sessions = smod.list_active_sessions(22)
    # The revoked session should not appear
    assert all(s.get("token_hash") != smod._hash_token(token) for s in sessions)


def test_list_active_sessions_empty_user(tmp_db: object) -> None:
    sessions = smod.list_active_sessions(9999)
    assert sessions == []
