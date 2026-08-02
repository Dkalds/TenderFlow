"""Tests for db/events.py — domain event sourcing functions."""

from __future__ import annotations


def test_append_event_returns_positive_id(tmp_db):
    """append_event returns a positive integer event ID."""
    from db.events import append_event

    event_id = append_event("test.event", "42", "licitacion", {"key": "val"})
    assert isinstance(event_id, int)
    assert event_id > 0


def test_append_event_with_actor(tmp_db):
    """append_event stores actor_id when provided."""
    db_mod, _ = tmp_db

    from db.events import append_event

    # actor_id es el id numérico del usuario: domain_events.actor_id es INTEGER
    # en ambos motores. Antes el test pasaba "user1" y funcionaba solo porque
    # SQLite no aplica tipos estrictos (ADR-018).
    append_event("login", "user1", "user", {}, actor_id=42)

    with db_mod.connect_read() as c:
        rows = c.execute("SELECT actor_id FROM domain_events").fetchall()

    assert rows[0][0] == 42


def test_get_events_returns_appended_events(tmp_db):
    """get_events returns events for the given aggregate in order."""
    from db.events import append_event, get_events

    append_event("item.created", "100", "licitacion", {"title": "test"})
    append_event("item.updated", "100", "licitacion", {"title": "updated"})

    events = get_events("licitacion", "100")
    assert len(events) == 2
    assert events[0]["event_type"] == "item.created"
    assert events[1]["event_type"] == "item.updated"


def test_get_events_empty_for_unknown_aggregate(tmp_db):
    """get_events returns [] for an aggregate with no events."""
    from db.events import get_events

    result = get_events("licitacion", "nonexistent")
    assert result == []


def test_get_events_filter_by_event_type(tmp_db):
    """get_events with event_type filter returns only matching events."""
    from db.events import append_event, get_events

    append_event("login", "u1", "user", {})
    append_event("logout", "u1", "user", {})
    append_event("login", "u1", "user", {})

    logins = get_events("user", "u1", event_type="login")
    assert len(logins) == 2
    assert all(e["event_type"] == "login" for e in logins)


def test_get_events_payload_is_deserialized(tmp_db):
    """get_events deserializes payload_json into a dict."""
    from db.events import append_event, get_events

    append_event("data.set", "agg1", "thing", {"foo": "bar", "count": 42})

    events = get_events("thing", "agg1")
    assert len(events) == 1
    assert events[0]["payload"]["foo"] == "bar"
    assert events[0]["payload"]["count"] == 42


def test_get_events_by_type_returns_all_matching(tmp_db):
    """get_events_by_type returns events for the given type across aggregates."""
    from db.events import append_event, get_events_by_type

    append_event("feedback.submitted", "1", "user", {"expediente": "E-001"})
    append_event("feedback.submitted", "2", "user", {"expediente": "E-002"})
    append_event("other.event", "3", "user", {})

    events = get_events_by_type("feedback.submitted")
    assert len(events) == 2
    assert all(e["event_type"] == "feedback.submitted" for e in events)


def test_cache_invalidation_event_is_visible_to_a_new_read(tmp_db):
    """La señal persistida se observa desde otra conexión del pool."""
    from db.events import (
        append_cache_invalidation_event,
        get_latest_cache_invalidation_timestamp,
    )

    assert get_latest_cache_invalidation_timestamp() == 0.0
    event_id = append_cache_invalidation_event()

    assert event_id > 0
    assert get_latest_cache_invalidation_timestamp() > 0.0


def test_replay_watchlist_reconstructs_state(tmp_db):
    """replay_watchlist returns active items after add/remove events."""
    from db.events import append_event, replay_watchlist

    append_event("watchlist.item_added", "u1", "user", {"id_externo": "E-001", "title": "A"})
    append_event("watchlist.item_added", "u1", "user", {"id_externo": "E-002", "title": "B"})
    append_event("watchlist.item_removed", "u1", "user", {"id_externo": "E-001"})

    state = replay_watchlist("u1")
    assert len(state) == 1
    assert state[0]["id_externo"] == "E-002"


def test_replay_feedback_returns_last_write_wins(tmp_db):
    """replay_feedback returns the last feedback per expediente."""
    from db.events import append_event, replay_feedback

    append_event("feedback.submitted", "u1", "user", {"expediente": "EXP-1", "relevante": True})
    append_event("feedback.submitted", "u2", "user", {"expediente": "EXP-1", "relevante": False})

    result = replay_feedback()
    assert len(result) == 1
    assert result[0]["expediente"] == "EXP-1"
    assert result[0]["relevante"] is False  # last write wins
