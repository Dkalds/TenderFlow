"""Tests para api/auth.py — hashing, creación, revocación y scope checks."""

from __future__ import annotations

import hashlib

import pytest

# ── hash_api_key ─────────────────────────────────────────────────────────────


def test_hash_api_key_plain_sha256(monkeypatch):
    """Sin API_HMAC_SECRET usa SHA-256 plain."""
    from pydantic import SecretStr

    import config as _cfg

    monkeypatch.setattr(_cfg.settings, "API_HMAC_SECRET", SecretStr(""))

    from api.auth import hash_api_key

    raw = "test-key-12345"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert hash_api_key(raw) == expected


def test_hash_api_key_hmac_with_secret(monkeypatch):
    """Con API_HMAC_SECRET usa HMAC-SHA256."""
    import hmac as _hmac

    from pydantic import SecretStr

    import config as _cfg

    monkeypatch.setattr(_cfg.settings, "API_HMAC_SECRET", SecretStr("supersecret"))

    from api.auth import hash_api_key

    raw = "test-key-12345"
    expected = _hmac.new(b"supersecret", raw.encode(), hashlib.sha256).hexdigest()
    assert hash_api_key(raw) == expected


def test_hash_api_key_deterministic(monkeypatch):
    """El mismo input siempre produce el mismo hash."""
    monkeypatch.setenv("API_HMAC_SECRET", "")

    from api.auth import hash_api_key

    raw = "my-api-key"
    assert hash_api_key(raw) == hash_api_key(raw)


def test_hash_api_key_different_inputs_differ(monkeypatch):
    """Inputs distintos → hashes distintos."""
    monkeypatch.setenv("API_HMAC_SECRET", "")

    from api.auth import hash_api_key

    assert hash_api_key("key-A") != hash_api_key("key-B")


# ── AuthContext.has_scope ─────────────────────────────────────────────────────


def test_auth_context_wildcard_grants_any_scope():
    from api.auth import AuthContext

    ctx = AuthContext(key_hash="abc", key_id=1, scopes=frozenset({"*"}))
    assert ctx.has_scope("admin")
    assert ctx.has_scope("webhooks:write")
    assert ctx.has_scope("nonexistent")


def test_auth_context_specific_scope_granted():
    from api.auth import AuthContext

    ctx = AuthContext(key_hash="abc", key_id=1, scopes=frozenset({"read", "webhooks:read"}))
    assert ctx.has_scope("read")
    assert ctx.has_scope("webhooks:read")


def test_auth_context_specific_scope_denied():
    from api.auth import AuthContext

    ctx = AuthContext(key_hash="abc", key_id=1, scopes=frozenset({"read"}))
    assert not ctx.has_scope("admin")
    assert not ctx.has_scope("webhooks:write")


# ── create_api_key + revoke_api_key ──────────────────────────────────────────


def test_create_api_key_returns_token(api_db):
    """create_api_key devuelve un token en bruto no vacío."""
    from api.auth import create_api_key

    token = create_api_key("test-integration")
    assert isinstance(token, str)
    assert len(token) > 10


def test_revoke_api_key_deactivates(api_db):
    """Revocar una key existente devuelve True."""
    from api.auth import create_api_key, hash_api_key, revoke_api_key

    token = create_api_key("revoke-test")
    key_hash = hash_api_key(token)
    assert revoke_api_key(key_hash) is True


def test_revoke_api_key_nonexistent_returns_false(api_db):
    """Revocar una key que no existe devuelve False."""
    from api.auth import revoke_api_key

    assert revoke_api_key("0" * 64) is False


def test_create_api_key_with_expiry(api_db):
    """create_api_key acepta expires_days sin error."""
    from api.auth import create_api_key

    token = create_api_key("expiry-test", expires_days=30)
    assert isinstance(token, str)
    assert len(token) > 10


def test_create_api_key_requires_owner_outside_dev(api_db, monkeypatch):
    """Una clave nueva en producción no puede quedar sin propietario."""
    import config as _cfg
    from api.auth import create_api_key

    monkeypatch.setattr(_cfg.settings, "ENV", "prod")
    with pytest.raises(ValueError, match="must be bound"):
        create_api_key("unbound-production-key")
