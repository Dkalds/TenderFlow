"""Tests for db/model_registry.py — model version lifecycle."""

from __future__ import annotations

from db.model_registry import (
    activate_version,
    feedbacks_since_last_train,
    get_active,
    list_versions,
    register_version,
)


def test_register_version(tmp_db):
    _db_mod, _ = tmp_db
    v = register_version(
        name="test_model",
        path="/tmp/m.pkl",  # noqa: S108
        sha256="aaa",
        metrics={"f1": 0.9},
        n_samples=100,
    )
    assert v == 1


def test_get_active(tmp_db):
    _db_mod, _ = tmp_db
    register_version(
        name="test_model",
        path="/tmp/m.pkl",  # noqa: S108
        sha256="aaa",
        activate=True,
    )
    active = get_active("test_model")
    assert active is not None
    assert active["version"] == 1
    assert active["is_active"] == 1


def test_activate_rollback(tmp_db):
    _db_mod, _ = tmp_db
    register_version(name="m", path="p1", sha256="a1", activate=True)
    register_version(name="m", path="p2", sha256="a2", activate=True)
    assert get_active("m")["version"] == 2
    assert activate_version("m", 1) is True
    assert get_active("m")["version"] == 1


def test_list_versions(tmp_db):
    _db_mod, _ = tmp_db
    for i in range(3):
        register_version(name="m", path=f"p{i}", sha256=f"s{i}")
    versions = list_versions("m")
    assert len(versions) == 3
    # Ordered DESC by version
    assert versions[0]["version"] > versions[-1]["version"]


def test_feedbacks_since_last_train(tmp_db):
    _db_mod, _ = tmp_db
    register_version(name="sap_classifier", path="p", sha256="s", activate=True)
    # Push trained_at into the past so feedbacks inserted "now" are strictly after it.
    from db.database import connect

    with connect() as c:
        c.execute(
            "UPDATE model_versions SET trained_at = '2020-01-01T00:00:00' "
            "WHERE name = 'sap_classifier'"
        )
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, created_at) "
            "VALUES (?, ?, datetime('now'))",
            ("EXP-001", 1),
        )
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, created_at) "
            "VALUES (?, ?, datetime('now'))",
            ("EXP-002", 0),
        )
    count = feedbacks_since_last_train("sap_classifier")
    assert count == 2


def test_get_active_nonexistent(tmp_db):
    _db_mod, _ = tmp_db
    assert get_active("nonexistent_model") is None


def test_activate_nonexistent_version(tmp_db):
    _db_mod, _ = tmp_db
    assert activate_version("nonexistent", 999) is False
