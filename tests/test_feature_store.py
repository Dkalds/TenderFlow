"""Tests for db/feature_store.py — lightweight feature cache."""

from __future__ import annotations

from db.feature_store import (
    feature_stats,
    get_feature,
    get_features_bulk,
    purge_stale_features,
    set_feature,
)


def test_set_get_feature(tmp_db):
    _db_mod, _ = tmp_db
    set_feature("licitacion", "LIC-001", "embedding_v1", [0.1, 0.2, 0.3])
    result = get_feature("licitacion", "LIC-001", "embedding_v1")
    assert result == [0.1, 0.2, 0.3]


def test_bulk_retrieval(tmp_db):
    _db_mod, _ = tmp_db
    ids = ["A", "B", "C"]
    for eid in ids:
        set_feature("licitacion", eid, "score", {"v": eid})
    bulk = get_features_bulk("licitacion", ids, "score")
    assert set(bulk.keys()) == set(ids)
    assert bulk["B"] == {"v": "B"}


def test_versioning(tmp_db):
    _db_mod, _ = tmp_db
    set_feature("licitacion", "X", "emb", [1.0], version="v1")
    set_feature("licitacion", "X", "emb", [2.0], version="v2")
    assert get_feature("licitacion", "X", "emb", version="v1") == [1.0]
    assert get_feature("licitacion", "X", "emb", version="v2") == [2.0]


def test_purge_stale(tmp_db):
    _db_mod, _ = tmp_db
    # Insert a feature with old timestamp
    import json

    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT INTO feature_store "
            "(entity_type, entity_id, feature_name, value_json, version, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("licitacion", "OLD", "emb", json.dumps([0.0]), "v1", "2020-01-01T00:00:00"),
        )
    # Insert a recent one normally
    set_feature("licitacion", "NEW", "emb", [1.0])
    purged = purge_stale_features(older_than_days=1)
    assert purged >= 1
    assert get_feature("licitacion", "OLD", "emb") is None
    assert get_feature("licitacion", "NEW", "emb") == [1.0]


def test_stats(tmp_db):
    _db_mod, _ = tmp_db
    set_feature("licitacion", "A", "score", 1.0)
    set_feature("licitacion", "B", "score", 2.0)
    set_feature("fragment", "C", "emb", [0.1])
    stats = feature_stats()
    assert len(stats) >= 2
    # Each stat entry has expected keys
    for s in stats:
        assert "entity_type" in s
        assert "feature_name" in s
        assert "n" in s
