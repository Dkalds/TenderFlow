"""Tests para shared/auth_core.py — nonce store, OAuth state, verify_password."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# _TTLCacheNonceStore
# ---------------------------------------------------------------------------


def test_ttlcache_nonce_store_add_and_contains():
    from shared.auth_core import _TTLCacheNonceStore

    store = _TTLCacheNonceStore(ttl=60)
    assert not store.contains("abc123")
    store.add("abc123", 60)
    assert store.contains("abc123")


def test_ttlcache_nonce_store_no_false_positive():
    from shared.auth_core import _TTLCacheNonceStore

    store = _TTLCacheNonceStore(ttl=60)
    store.add("nonce_A", 60)
    assert not store.contains("nonce_B")


def test_ttlcache_nonce_store_expiry_lazy():
    """El dict de fallback limpia las entradas expiradas en contains()."""
    from shared.auth_core import _TTLCacheNonceStore

    store = _TTLCacheNonceStore(ttl=1)
    # Forzar uso del fallback dict en lugar de TTLCache
    store._use_ttlcache = False
    store._cache = {}

    store.add("old_nonce", 1)
    # Expirar manualmente
    store._cache["old_nonce"] = time.time() - 10
    assert not store.contains("old_nonce")


# ---------------------------------------------------------------------------
# _RedisNonceStore
# ---------------------------------------------------------------------------


def test_redis_nonce_store_add_and_contains():
    """Usa mock de Redis — verifica llamadas a set() y exists()."""
    store = _make_redis_store_with_mock()
    store._client.set.return_value = True
    store.add("abc", ttl_seconds=300)
    store._client.set.assert_called_once()
    store._client.exists.return_value = 1
    assert store.contains("abc")


def _make_redis_store_with_mock():
    """Crea un _RedisNonceStore con cliente Redis mockeado."""
    from shared.auth_core import _RedisNonceStore, _TTLCacheNonceStore

    store = _RedisNonceStore.__new__(_RedisNonceStore)
    store._prefix = "oauth_nonce:"
    store._client = MagicMock()
    store._fallback = _TTLCacheNonceStore()
    return store


def test_redis_nonce_store_contains_true():
    store = _make_redis_store_with_mock()
    store._client.exists.return_value = 1
    assert store.contains("nonce123")
    store._client.exists.assert_called_once_with("oauth_nonce:nonce123")


def test_redis_nonce_store_contains_false():
    store = _make_redis_store_with_mock()
    store._client.exists.return_value = 0
    assert not store.contains("nonce123")


def test_redis_nonce_store_add_calls_set_nx():
    store = _make_redis_store_with_mock()
    store.add("nonce_xyz", 600)
    store._client.set.assert_called_once_with("oauth_nonce:nonce_xyz", "1", nx=True, ex=600)


def test_redis_nonce_store_contains_uses_fallback_on_error():
    """Si Redis lanza excepción, contains() delega al fallback in-memory (fail-closed)."""
    store = _make_redis_store_with_mock()
    store._client.exists.side_effect = ConnectionError("Redis down")
    # Nonce not in fallback → False (but via fallback, not fail-open)
    assert not store.contains("nonce123")
    # Add to fallback, then verify contains returns True even with Redis down
    store._fallback.add("nonce123", 600)
    assert store.contains("nonce123")


def test_redis_nonce_store_add_fail_silent():
    """Si Redis lanza excepción en add(), no propaga y escribe al fallback."""
    store = _make_redis_store_with_mock()
    store._client.set.side_effect = ConnectionError("Redis down")
    store.add("nonce_xyz", 600)  # no debe lanzar
    # Verify fallback has the nonce
    assert store._fallback.contains("nonce_xyz")


def test_redis_nonce_store_add_always_writes_fallback():
    """add() escribe al fallback incluso cuando Redis funciona."""
    store = _make_redis_store_with_mock()
    store._client.set.return_value = True
    store.add("nonce_abc", 300)
    assert store._fallback.contains("nonce_abc")


def test_redis_nonce_store_replay_detected_via_fallback_on_redis_failure():
    """Anti-replay funciona via fallback cuando Redis cae después del add()."""
    store = _make_redis_store_with_mock()
    store._client.set.return_value = True
    store._client.exists.return_value = 0
    # First: add nonce (writes to both Redis and fallback)
    store.add("replay_nonce", 600)
    # Now Redis goes down
    store._client.exists.side_effect = ConnectionError("Redis down")
    # contains() should find it in fallback
    assert store.contains("replay_nonce")


# ---------------------------------------------------------------------------
# _get_nonce_store singleton + reset
# ---------------------------------------------------------------------------


def test_get_nonce_store_returns_ttlcache_without_redis(monkeypatch):
    import config
    from shared.auth_core import _get_nonce_store, _reset_nonce_store, _TTLCacheNonceStore

    _reset_nonce_store()
    monkeypatch.setattr(config.settings, "REDIS_URL", "")
    store = _get_nonce_store()
    assert isinstance(store, _TTLCacheNonceStore)
    _reset_nonce_store()


def test_get_nonce_store_returns_redis_when_configured(monkeypatch):
    import config
    from shared.auth_core import _get_nonce_store, _RedisNonceStore, _reset_nonce_store

    _reset_nonce_store()
    monkeypatch.setattr(config.settings, "REDIS_URL", "redis://localhost:6379/0")

    with patch("shared.auth_core._RedisNonceStore") as MockRedisStore:
        instance = MagicMock(spec=_RedisNonceStore)
        MockRedisStore.return_value = instance
        store = _get_nonce_store()
        assert store is instance

    _reset_nonce_store()


def test_get_nonce_store_falls_back_to_ttlcache_on_redis_error(monkeypatch):
    import config
    from shared.auth_core import _get_nonce_store, _reset_nonce_store, _TTLCacheNonceStore

    _reset_nonce_store()
    monkeypatch.setattr(config.settings, "REDIS_URL", "redis://bad-host:6379/0")

    with patch("shared.auth_core._RedisNonceStore", side_effect=Exception("conn failed")):
        store = _get_nonce_store()
        assert isinstance(store, _TTLCacheNonceStore)

    _reset_nonce_store()


# ---------------------------------------------------------------------------
# verify_oauth_state — anti-replay
# ---------------------------------------------------------------------------


def test_verify_oauth_state_blocks_replay(monkeypatch):
    """El mismo state no puede usarse dos veces."""
    import config
    from shared.auth_core import (
        _reset_nonce_store,
        generate_oauth_state,
        verify_oauth_state,
    )

    _reset_nonce_store()
    monkeypatch.setattr(config.settings, "REDIS_URL", "")
    monkeypatch.setattr(
        config.settings,
        "SIGNING_KEY",
        __import__("pydantic").SecretStr("test-key-32-chars-exactly-ok!!"),
    )

    state = generate_oauth_state()
    assert verify_oauth_state(state) is True
    assert verify_oauth_state(state) is False  # replay detectado
    _reset_nonce_store()


def test_verify_oauth_state_invalid_signature():
    from shared.auth_core import generate_oauth_state, verify_oauth_state

    state = generate_oauth_state()
    tampered = state[:-4] + "0000"
    assert verify_oauth_state(tampered) is False


def test_verify_oauth_state_expired():
    from shared.auth_core import generate_oauth_state, verify_oauth_state

    state = generate_oauth_state()
    # max_age = 0 → cualquier state ha expirado
    assert verify_oauth_state(state, max_age=0) is False


def test_verify_oauth_state_empty():
    from shared.auth_core import verify_oauth_state

    assert verify_oauth_state("") is False
    assert verify_oauth_state("bad:format") is False


def test_oauth_state_nonce_is_extractable_only_from_expected_format():
    from shared.auth_core import generate_oauth_state, oauth_state_nonce

    nonce = oauth_state_nonce(generate_oauth_state())
    assert nonce is not None
    assert len(nonce) == 32
    assert oauth_state_nonce("not:a:nonce") is None


def test_google_id_token_nonce_must_match_authorization_flow():
    from shared.auth_core import validate_google_id_token

    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": "client-id",
        "sub": "google-subject",
        "exp": int(time.time()) + 300,
        "email_verified": True,
        "nonce": "expected-nonce",
    }
    assert validate_google_id_token(claims, audience="client-id", expected_nonce="expected-nonce")
    assert not validate_google_id_token(claims, audience="client-id", expected_nonce="other-nonce")


def test_verify_google_id_token_accepts_real_jwks_shape_without_x5c():
    """Regresión: el JWKS v3 real de Google trae RSA n/e, nunca x5c.

    Antes de este fix, verify_google_id_token exigía "x5c" (cadena de
    certificados X.509) en cada entrada del JWKS — un campo que el endpoint
    real de Google jamás incluye — así que ninguna clave pasaba el filtro y
    *todo* login con Google fallaba con "Google JWKS response had no usable
    keys" (visto en producción como 'google_id_token_signature_invalid').
    """
    import base64
    import json

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    import shared.auth_core as auth_core

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    def _b64url_uint(value: int) -> str:
        length = (value.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(value.to_bytes(length, "big")).rstrip(b"=").decode()

    def _b64url_json(obj: dict) -> str:
        data = json.dumps(obj, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    kid = "test-kid-1"
    encoded_header = _b64url_json({"alg": "RS256", "kid": kid})
    encoded_claims = _b64url_json(
        {
            "iss": "https://accounts.google.com",
            "aud": "client-id",
            "sub": "google-subject",
            "exp": int(time.time()) + 300,
            "email_verified": True,
            "nonce": "expected-nonce",
        }
    )
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    jwt_token = f"{encoded_header}.{encoded_claims}.{encoded_signature}"

    jwks_response = {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": kid,
                "n": _b64url_uint(public_numbers.n),
                "e": _b64url_uint(public_numbers.e),
                # Deliberadamente sin "x5c": el endpoint v3 real de Google no lo trae.
            }
        ]
    }
    mock_response = MagicMock()
    mock_response.json.return_value = jwks_response
    mock_response.raise_for_status.return_value = None

    auth_core._google_jwks_cache = None
    try:
        with patch("httpx.get", return_value=mock_response):
            result = auth_core.verify_google_id_token(
                jwt_token, audience="client-id", expected_nonce="expected-nonce"
            )
        assert result is not None
        assert result["sub"] == "google-subject"
    finally:
        auth_core._google_jwks_cache = None
