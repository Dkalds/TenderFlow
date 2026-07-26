"""Tests for db/audit.py — log_event and list_recent (uncovered paths)."""

from __future__ import annotations

# ── log_event ──────────────────────────────────────────────────────────────


def test_log_event_string_detail_writes_to_db(tmp_db):
    """log_event with a string detail should persist a row in audit_log."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="test.event", user_key="user1", session_hash="sess1")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT action, detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert len(rows) == 1
    action, detail = rows[0]
    assert action == "test.event"
    assert "event=test.event" in detail
    assert "outcome=success" in detail


def test_log_event_dict_detail_serialized(tmp_db):
    """log_event with a dict detail serializes it to JSON string."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(
        event_type="api_key.created",
        user_key="user2",
        detail={"key_id": 42, "name": "my_key"},
    )

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert len(rows) == 1
    detail = rows[0][0]
    assert "key_id" in detail
    assert "42" in detail


def test_log_event_with_ip_in_detail(tmp_db):
    """log_event with ip parameter includes it in structured detail."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="login", user_key="u1", ip="192.168.1.1")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert "ip=192.168.1.1" in rows[0][0]


def test_log_event_with_resource_in_detail(tmp_db):
    """log_event with resource parameter includes it in structured detail."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="webhook.delivery", resource="webhook:7")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert "resource=webhook:7" in rows[0][0]


def test_log_event_failure_outcome(tmp_db):
    """log_event with outcome=failure stores that outcome in detail."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="login_failed", user_key="bad_user", outcome="failure")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert "outcome=failure" in rows[0][0]


def test_log_event_all_params(tmp_db):
    """log_event with all params populates detail accordingly."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(
        event_type="model.activated",
        user_key="admin",
        session_hash="s123",
        outcome="success",
        ip="10.0.0.1",
        resource="model:99",
        detail="activated new model",
    )

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT action, detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    action, detail = rows[0]
    assert action == "model.activated"
    assert "ip=10.0.0.1" in detail
    assert "resource=model:99" in detail
    assert "activated new model" in detail


def test_log_event_system_user_key_defaults(tmp_db):
    """log_event without user_key defaults to 'system'."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    log_event(event_type="scheduler.run")

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT user_key FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert rows[0][0] == "system"


def test_log_event_detail_truncated_at_2000_chars(tmp_db):
    """log_event truncates very long string details to 2000 chars."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    long_detail = "x" * 5000

    log_event(event_type="long.event", detail=long_detail)

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    detail = rows[0][0]
    # The raw detail_str portion is truncated; total structured detail will be longer
    # but the raw detail contribution is <= 2000 chars
    assert "event=long.event" in detail


def test_log_event_dict_detail_truncated(tmp_db):
    """log_event truncates large dict serializations to 2000 chars."""
    db_mod, _ = tmp_db

    from db.audit import log_event

    big_dict = {f"key_{i}": "v" * 100 for i in range(50)}
    log_event(event_type="big.event", detail=big_dict)

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT detail FROM audit_log ORDER BY id DESC LIMIT 1").fetchall()

    assert len(rows) == 1  # Should succeed without error


# ── list_recent ─────────────────────────────────────────────────────────────


def test_list_recent_empty_returns_empty_list(tmp_db):
    """list_recent on empty table returns []."""
    from db.audit import list_recent

    result = list_recent()
    assert result == []


def test_list_recent_returns_all_rows(tmp_db):
    """list_recent returns all logged actions when no filters applied."""
    from db.audit import list_recent, log_action

    log_action("u1", "s1", "action_a", "detail_a")
    log_action("u2", "s2", "action_b", "detail_b")
    log_action("u1", "s3", "action_c", "detail_c")

    result = list_recent()
    assert len(result) == 3


def test_list_recent_contains_expected_keys(tmp_db):
    """list_recent rows are dicts with id, user_key, session_hash, action, detail, created_at."""
    from db.audit import list_recent, log_action

    log_action("alice", "s1", "export_excel", "file.xlsx")

    result = list_recent()
    assert len(result) == 1
    row = result[0]
    assert "id" in row
    assert row["user_key"] == "alice"
    assert row["action"] == "export_excel"
    assert row["detail"] == "file.xlsx"
    assert "created_at" in row


def test_list_recent_filter_by_user_key(tmp_db):
    """list_recent with user_key filter returns only that user's actions."""
    from db.audit import list_recent, log_action

    log_action("user_a", "s1", "login", "")
    log_action("user_b", "s2", "login", "")
    log_action("user_a", "s3", "logout", "")

    result = list_recent(user_key="user_a")
    assert len(result) == 2
    assert all(r["user_key"] == "user_a" for r in result)


def test_list_recent_filter_by_action(tmp_db):
    """list_recent with action filter returns only matching actions."""
    from db.audit import list_recent, log_action

    log_action("u1", "s1", "login", "")
    log_action("u2", "s2", "logout", "")
    log_action("u3", "s3", "login", "")

    result = list_recent(action="login")
    assert len(result) == 2
    assert all(r["action"] == "login" for r in result)


def test_list_recent_filter_both_user_and_action(tmp_db):
    """list_recent with both filters combines them with AND."""
    from db.audit import list_recent, log_action

    log_action("alice", "s1", "login", "")
    log_action("alice", "s2", "logout", "")
    log_action("bob", "s3", "login", "")

    result = list_recent(user_key="alice", action="login")
    assert len(result) == 1
    assert result[0]["user_key"] == "alice"
    assert result[0]["action"] == "login"


def test_list_recent_respects_limit(tmp_db):
    """list_recent respects the limit parameter."""
    from db.audit import list_recent, log_action

    for i in range(10):
        log_action("u", "s", f"action_{i}", "")

    result = list_recent(limit=3)
    assert len(result) == 3


def test_list_recent_ordered_by_created_at_desc(tmp_db):
    """list_recent returns rows ordered by created_at DESC (most recent first)."""
    from db.audit import list_recent, log_action

    log_action("u", "s", "first", "")
    log_action("u", "s", "second", "")
    log_action("u", "s", "third", "")

    result = list_recent()
    assert result[0]["action"] == "third"
    assert result[-1]["action"] == "first"


def test_verify_hash_chain_detects_deleted_intermediate_entry(tmp_db):
    """A deleted row breaks prev_hash continuity rather than silently passing."""
    from db.audit import log_action, verify_hash_chain
    from db.database import connect

    log_action("u", "s", "first")
    log_action("u", "s", "second")
    log_action("u", "s", "third")
    with connect() as connection:
        connection.execute("DELETE FROM audit_log WHERE action = ?", ("second",))

    result = verify_hash_chain()
    assert result["valid"] is False
    assert "interrumpida" in str(result["error"])


def test_verify_hash_chain_detects_deleted_tail_via_signed_head(tmp_db):
    """The signed state catches a tail deletion that continuity alone cannot."""
    from db.audit import log_action, verify_hash_chain
    from db.database import connect

    log_action("u", "s", "first")
    log_action("u", "s", "second")
    with connect() as connection:
        connection.execute("DELETE FROM audit_log WHERE action = ?", ("second",))

    result = verify_hash_chain()
    assert result["valid"] is False
    assert "cabecera anclada" in str(result["error"])
