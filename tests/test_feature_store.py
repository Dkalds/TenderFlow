"""Tests for db/feature_store.py — lightweight feature cache."""

from __future__ import annotations

from db.feature_store import get_features_bulk, set_feature


def test_set_get_feature(tmp_db):
    _db_mod, _ = tmp_db
    set_feature("licitacion", "LIC-001", "embedding_v1", [0.1, 0.2, 0.3])
    result = get_features_bulk("licitacion", ["LIC-001"], "embedding_v1")
    assert result == {"LIC-001": [0.1, 0.2, 0.3]}


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
    assert get_features_bulk("licitacion", ["X"], "emb", version="v1") == {"X": [1.0]}
    assert get_features_bulk("licitacion", ["X"], "emb", version="v2") == {"X": [2.0]}
