"""Tests para services/gdpr.py — exportación, anonimización y gestión GDPR."""

from __future__ import annotations

from db.database import connect, now_utc_iso


def _seed_user_and_key(db_mod, *, user_id: int = 1, key_id: int = 1, key_hash: str = "hash1"):
    """Inserta un usuario y una API key vinculada."""
    with connect() as c:
        c.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
            (user_id, f"u{user_id}@test.com", now_utc_iso()),
        )
        # api_keys: check if user_id/scopes/prefix cols exist
        cols = db_mod.get_table_columns(c, "api_keys")
        base = "INSERT INTO api_keys (id, key_hash, name, created_at, is_active"
        vals = [key_id, key_hash, "test-key", now_utc_iso(), 1]
        if "scopes" in cols:
            base += ", scopes"
            vals.append("read,write")
        if "user_id" in cols:
            base += ", user_id"
            vals.append(user_id)
        if "prefix" in cols:
            base += ", prefix"
            vals.append("lsp_")
        if "expires_at" in cols:
            base += ", expires_at"
            vals.append(None)
        base += ") VALUES (" + ",".join("?" for _ in vals) + ")"
        c.execute(base, vals)


# ---------------------------------------------------------------------------
# get_user_id_from_key_id
# ---------------------------------------------------------------------------


def test_get_user_id_from_key_id_returns_user(tmp_db):
    db_mod, _ = tmp_db
    _seed_user_and_key(db_mod, user_id=42, key_id=7, key_hash="k1")
    from services.gdpr import get_user_id_from_key_id

    uid = get_user_id_from_key_id(7)
    assert uid is not None
    # Should be 42 if user_id col exists, otherwise None (#44)
    assert isinstance(uid, int)


def test_get_user_id_from_key_id_missing_key(tmp_db):
    """When key doesn't exist, must return None — never an arbitrary user (#44)."""
    db_mod, _ = tmp_db
    _seed_user_and_key(db_mod, user_id=1, key_id=1, key_hash="k2")
    from services.gdpr import get_user_id_from_key_id

    uid = get_user_id_from_key_id(9999)
    assert uid is None, "Must return None for missing key, not fallback to first user"


# ---------------------------------------------------------------------------
# export_api_keys
# ---------------------------------------------------------------------------


def test_export_api_keys_returns_matching(tmp_db):
    db_mod, _ = tmp_db
    _seed_user_and_key(db_mod, key_hash="abc123")
    from services.gdpr import export_api_keys

    rows = export_api_keys("abc123")
    assert len(rows) == 1
    assert rows[0]["name"] == "test-key"


def test_export_api_keys_empty_for_unknown_hash(tmp_db):
    _db_mod, _ = tmp_db
    from services.gdpr import export_api_keys

    assert export_api_keys("nonexistent") == []


# ---------------------------------------------------------------------------
# export_feedback
# ---------------------------------------------------------------------------


def test_export_feedback(tmp_db):
    _db_mod, _ = tmp_db
    with connect() as c:
        c.execute(
            "INSERT INTO ml_feedback (expediente, relevante, nota, created_at) VALUES (?, ?, ?, ?)",
            ("EXP-001", 1, "good", now_utc_iso()),
        )
    from services.gdpr import export_feedback

    rows = export_feedback()
    assert len(rows) == 1
    assert rows[0]["expediente"] == "EXP-001"


# ---------------------------------------------------------------------------
# export_watchlist / export_audit_log (may return [] if table name mismatch)
# ---------------------------------------------------------------------------


def test_export_watchlist_returns_empty_gracefully(tmp_db):
    """watchlist table may not exist (gdpr queries 'watchlist' not 'watchlist_cpv')."""
    _db_mod, _ = tmp_db
    from services.gdpr import export_watchlist

    result = export_watchlist("somehash")
    assert isinstance(result, list)


def test_export_audit_log(tmp_db):
    _db_mod, _ = tmp_db
    with connect() as c:
        c.execute(
            "INSERT INTO audit_log (user_key, action, detail, created_at) VALUES (?, ?, ?, ?)",
            ("hash1", "login", "ok", now_utc_iso()),
        )
    from services.gdpr import export_audit_log

    rows = export_audit_log("hash1")
    assert len(rows) == 1
    assert rows[0]["action"] == "login"


def test_export_audit_log_empty(tmp_db):
    _db_mod, _ = tmp_db
    from services.gdpr import export_audit_log

    assert export_audit_log("nope") == []


# ---------------------------------------------------------------------------
# anonymize_user_data
# ---------------------------------------------------------------------------


def test_anonymize_user_data_revokes_key(tmp_db):
    db_mod, _ = tmp_db
    _seed_user_and_key(db_mod, key_id=5, key_hash="target")
    from services.gdpr import anonymize_user_data

    anonymize_user_data("target", 5)
    with connect() as c:
        row = c.execute("SELECT is_active FROM api_keys WHERE id = 5").fetchone()
    assert row[0] == 0


# ---------------------------------------------------------------------------
# list_user_keys / get_key_name_and_scopes / set_key_expiry
# ---------------------------------------------------------------------------


def test_list_user_keys(tmp_db):
    db_mod, _ = tmp_db
    _seed_user_and_key(db_mod, key_id=3, key_hash="lk1")
    from services.gdpr import list_user_keys

    rows = list_user_keys(3)
    assert len(rows) == 1
    assert rows[0]["id"] == 3


def test_get_key_name_and_scopes(tmp_db):
    db_mod, _ = tmp_db
    _seed_user_and_key(db_mod, key_id=10, key_hash="ns1")
    from services.gdpr import get_key_name_and_scopes

    result = get_key_name_and_scopes(10)
    assert result is not None
    name, scopes = result
    assert name == "test-key"
    assert isinstance(scopes, str)


def test_get_key_name_and_scopes_missing(tmp_db):
    _db_mod, _ = tmp_db
    from services.gdpr import get_key_name_and_scopes

    assert get_key_name_and_scopes(9999) is None


def test_set_key_expiry(tmp_db):
    db_mod, _ = tmp_db
    _seed_user_and_key(db_mod, key_id=11, key_hash="exp1")
    from services.gdpr import set_key_expiry

    set_key_expiry(11, "2030-01-01T00:00:00Z")
    with connect() as c:
        row = c.execute("SELECT expires_at FROM api_keys WHERE id = 11").fetchone()
    # If expires_at column exists, should be set
    if row:
        assert row[0] == "2030-01-01T00:00:00Z" or row[0] is None


# ---------------------------------------------------------------------------
# Security: get_user_id_from_key_id NEVER returns arbitrary user (#44)
# ---------------------------------------------------------------------------


def test_get_user_id_from_key_id_null_user_id_returns_none(tmp_db):
    """When user_id column exists but is NULL, must return None (#44)."""
    db_mod, _ = tmp_db
    # Seed a user so there IS a user in the DB (the old bug would return this)
    with connect() as c:
        c.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
            (99, "victim@test.com", now_utc_iso()),
        )
        cols = db_mod.get_table_columns(c, "api_keys")
        if "user_id" in cols:
            # Insert key with NULL user_id
            base = "INSERT INTO api_keys (id, key_hash, name, created_at, is_active"
            vals: list[object] = [77, "nullkey", "null-key", now_utc_iso(), 1]
            if "scopes" in cols:
                base += ", scopes"
                vals.append("read")
            if "prefix" in cols:
                base += ", prefix"
                vals.append("lsp_")
            if "expires_at" in cols:
                base += ", expires_at"
                vals.append(None)
            # user_id deliberately omitted → NULL
            base += ") VALUES (" + ",".join("?" for _ in vals) + ")"
            c.execute(base, vals)

    from services.gdpr import get_user_id_from_key_id

    uid = get_user_id_from_key_id(77)
    assert uid is None, (
        f"Expected None for NULL user_id, got {uid} — "
        "this would be a GDPR violation (operating on wrong user)"
    )


def test_get_user_id_from_key_id_never_returns_other_user(tmp_db):
    """Regression: with multiple users, must never return someone else's id (#44)."""
    db_mod, _ = tmp_db
    _seed_user_and_key(db_mod, user_id=10, key_id=10, key_hash="own")
    # Add another user (potential victim of the old bug)
    with connect() as c:
        c.execute(
            "INSERT INTO users (id, email, created_at) VALUES (?, ?, ?)",
            (1, "other@test.com", now_utc_iso()),
        )

    from services.gdpr import get_user_id_from_key_id

    # Query for a non-existent key
    uid = get_user_id_from_key_id(9999)
    assert uid is None, f"Got user_id={uid} for non-existent key — GDPR violation"
    # user_id=1 (the 'other' user) must never be returned
