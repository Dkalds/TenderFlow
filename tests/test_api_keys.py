"""Tests for db/repositories/api_keys.py."""

from __future__ import annotations

import pytest


@pytest.fixture()
def db(tmp_db):
    yield tmp_db[0]


@pytest.fixture()
def repo(db):
    from db.repositories.api_keys import ApiKeyRepository

    return ApiKeyRepository()


# ── create ────────────────────────────────────────────────────────────────────


def test_create_returns_raw_token(db, repo):
    raw = repo.create("test-key")
    assert isinstance(raw, str)
    assert len(raw) > 20


def test_create_different_keys_each_time(db, repo):
    raw1 = repo.create("key-1")
    raw2 = repo.create("key-2")
    assert raw1 != raw2


def test_create_with_custom_scopes(db, repo):
    raw = repo.create("scoped-key", scopes="read:licitaciones")
    key_hash = repo._hash(raw)
    result = repo.get_by_hash(key_hash)
    assert result is not None


# ── get_by_hash ───────────────────────────────────────────────────────────────


def test_get_by_hash_returns_active_key(db, repo):
    raw = repo.create("active-key")
    key_hash = repo._hash(raw)
    result = repo.get_by_hash(key_hash)
    assert result is not None
    assert "id" in result


def test_get_by_hash_returns_none_for_unknown_hash(db, repo):
    result = repo.get_by_hash("nonexistent_hash_abc123")
    assert result is None


def test_get_by_hash_returns_none_after_revoke(db, repo):
    raw = repo.create("revoked-key")
    key_hash = repo._hash(raw)
    repo.revoke(key_hash)
    result = repo.get_by_hash(key_hash)
    assert result is None


# ── revoke ────────────────────────────────────────────────────────────────────


def test_revoke_returns_true_for_existing_key(db, repo):
    raw = repo.create("to-revoke")
    key_hash = repo._hash(raw)
    assert repo.revoke(key_hash) is True


def test_revoke_returns_false_for_nonexistent_key(db, repo):
    assert repo.revoke("no_such_hash_xyz") is False


def test_revoke_is_idempotent(db, repo):
    raw = repo.create("revoke-twice")
    key_hash = repo._hash(raw)
    repo.revoke(key_hash)
    # Second revoke: key still inactive; get_by_hash must return None both times
    repo.revoke(key_hash)  # should not raise
    assert repo.get_by_hash(key_hash) is None


# ── get_name ──────────────────────────────────────────────────────────────────


def test_get_name_returns_name_for_existing_key(db, repo):
    raw = repo.create("named-key")
    key_hash = repo._hash(raw)
    assert repo.get_name(key_hash) == "named-key"


def test_get_name_returns_none_for_unknown_hash(db, repo):
    assert repo.get_name("unknown_hash_xyz") is None


# ── update_last_used ──────────────────────────────────────────────────────────


def test_update_last_used_does_not_raise(db, repo):
    raw = repo.create("update-key")
    key_hash = repo._hash(raw)
    key_info = repo.get_by_hash(key_hash)
    assert key_info is not None
    repo.update_last_used(key_info["id"])  # should not raise


def test_update_last_used_bad_id_no_raise(db, repo):
    repo.update_last_used(99999)  # non-existent id — should not raise


# ── get_all_for_user ──────────────────────────────────────────────────────────


def test_get_all_for_user_returns_list(db, repo):
    result = repo.get_all_for_user(999)
    assert isinstance(result, list)


# ── _hash ─────────────────────────────────────────────────────────────────────


def test_hash_is_deterministic(db, repo):
    h1 = repo._hash("my_secret_token")
    h2 = repo._hash("my_secret_token")
    assert h1 == h2


def test_hash_different_inputs_different_outputs(db, repo):
    h1 = repo._hash("token_a")
    h2 = repo._hash("token_b")
    assert h1 != h2


def test_hash_returns_hex_string(db, repo):
    h = repo._hash("any_token")
    assert isinstance(h, str)
    assert len(h) == 64  # sha256 hex digest
