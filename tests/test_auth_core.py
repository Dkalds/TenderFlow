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


# ---------------------------------------------------------------------------
# _TTLCacheNonceStore fallback, _RedisNonceStore init
# ---------------------------------------------------------------------------


class TestTTLCacheNonceStoreFallback:
    """Lines 67-70: cachetools ImportError fallback."""

    def test_fallback_to_dict_when_cachetools_missing(self):
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "cachetools":
                raise ImportError("no cachetools")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            from shared.auth_core import _TTLCacheNonceStore

            store = _TTLCacheNonceStore.__new__(_TTLCacheNonceStore)
            store._ttl = 600
            store._cache = {}
            store._use_ttlcache = False

        # Test dict-based contains (lazy cleanup path)
        store._cache["old_nonce"] = time.time() - 1  # expired
        store._cache["fresh_nonce"] = time.time() + 600
        assert not store.contains("old_nonce")
        assert store.contains("fresh_nonce")

        # Test dict-based add
        store.add("new_nonce", 60)
        assert "new_nonce" in store._cache


class TestRedisNonceStore:
    """Lines 99-108: Redis nonce store init and operations."""

    @patch("redis.Redis")
    def test_init_and_contains_redis_hit(self, mock_redis_cls):
        mock_client = MagicMock()
        mock_redis_cls.from_url.return_value = mock_client
        mock_client.exists.return_value = 1

        from shared.auth_core import _RedisNonceStore

        store = _RedisNonceStore("redis://localhost")
        assert store.contains("abc")
        mock_client.exists.assert_called_once()

    @patch("redis.Redis")
    def test_contains_redis_miss_fallback(self, mock_redis_cls):
        mock_client = MagicMock()
        mock_redis_cls.from_url.return_value = mock_client
        mock_client.exists.return_value = 0

        from shared.auth_core import _RedisNonceStore

        store = _RedisNonceStore("redis://localhost")
        assert not store.contains("missing")

    @patch("redis.Redis")
    def test_contains_redis_error_fallback(self, mock_redis_cls):
        mock_client = MagicMock()
        mock_redis_cls.from_url.return_value = mock_client
        mock_client.exists.side_effect = Exception("conn refused")

        from shared.auth_core import _RedisNonceStore

        store = _RedisNonceStore("redis://localhost")
        assert not store.contains("x")

    @patch("redis.Redis")
    def test_add_writes_to_redis_and_fallback(self, mock_redis_cls):
        mock_client = MagicMock()
        mock_redis_cls.from_url.return_value = mock_client

        from shared.auth_core import _RedisNonceStore

        store = _RedisNonceStore("redis://localhost")
        store.add("nonce1", 300)
        mock_client.set.assert_called_once()
        assert store._fallback.contains("nonce1")

    @patch("redis.Redis")
    def test_add_redis_error_still_has_fallback(self, mock_redis_cls):
        mock_client = MagicMock()
        mock_redis_cls.from_url.return_value = mock_client
        mock_client.set.side_effect = Exception("write fail")

        from shared.auth_core import _RedisNonceStore

        store = _RedisNonceStore("redis://localhost")
        store.add("nonce2", 300)
        assert store._fallback.contains("nonce2")


class TestGetNonceStoreRedis:
    """Lines 157-158: _get_nonce_store with config import failure."""

    def setup_method(self):
        from shared import auth_core

        auth_core._nonce_store = None

    def teardown_method(self):
        from shared import auth_core

        auth_core._nonce_store = None

    def test_config_import_error_falls_to_ttlcache(self):
        from shared import auth_core

        with patch.dict("sys.modules", {"config": None}):
            store = auth_core._get_nonce_store()
        assert isinstance(store, auth_core._TTLCacheNonceStore)


# ---------------------------------------------------------------------------
# verify_password — argon2/bcrypt branches
# ---------------------------------------------------------------------------


class TestVerifyPassword:
    """Lines 186-218: verify_password branches."""

    def test_empty_hash_returns_false(self):
        from shared.auth_core import verify_password

        assert verify_password("test", "") is False

    @patch("argon2.PasswordHasher")
    def test_argon2_verify_match(self, mock_ph_cls):
        from shared.auth_core import verify_password

        mock_ph = MagicMock()
        mock_ph.verify.return_value = True
        mock_ph_cls.return_value = mock_ph
        assert verify_password("pass", "$argon2id$hash") is True

    @patch("argon2.PasswordHasher")
    def test_argon2_verify_mismatch(self, mock_ph_cls):
        from argon2.exceptions import VerifyMismatchError

        from shared.auth_core import verify_password

        mock_ph = MagicMock()
        mock_ph.verify.side_effect = VerifyMismatchError()
        mock_ph_cls.return_value = mock_ph
        assert verify_password("wrong", "$argon2id$hash") is False

    def test_argon2_generic_exception(self):
        from shared.auth_core import verify_password

        with patch("argon2.PasswordHasher") as mock_ph_cls:
            mock_ph_cls.return_value.verify.side_effect = RuntimeError("boom")
            assert verify_password("x", "$argon2id$hash") is False

    def test_bcrypt_verify_success(self):
        import bcrypt

        from shared.auth_core import verify_password

        hashed = bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode("utf-8")
        assert verify_password("testpass", hashed) is True

    def test_bcrypt_verify_failure(self):
        import bcrypt

        from shared.auth_core import verify_password

        hashed = bcrypt.hashpw(b"testpass", bcrypt.gensalt()).decode("utf-8")
        assert verify_password("wrong", hashed) is False

    def test_bcrypt_exception(self):
        from shared.auth_core import verify_password

        with patch("bcrypt.checkpw", side_effect=Exception("bad")):
            assert verify_password("x", "$2b$12$somehash") is False


# ---------------------------------------------------------------------------
# verify_oauth_state — timestamp parsing edge cases
# ---------------------------------------------------------------------------


class TestOAuthState:
    """Lines 278-279: ValueError in timestamp parsing."""

    def setup_method(self):
        from shared import auth_core

        auth_core._nonce_store = None

    def teardown_method(self):
        from shared import auth_core

        auth_core._nonce_store = None

    def test_verify_state_invalid_timestamp(self):
        from shared.auth_core import verify_oauth_state

        with patch("shared.auth_core.get_signing_key", return_value=b"key"):
            assert verify_oauth_state("nonce:notanumber:sig") is False

    def test_verify_state_expired(self):
        from shared.auth_core import verify_oauth_state

        old_ts = str(int(time.time()) - 9999)
        with patch("shared.auth_core.get_signing_key", return_value=b"key"):
            assert verify_oauth_state(f"nonce:{old_ts}:sig") is False


# ---------------------------------------------------------------------------
# csv_set, oauth_email_allowed, oauth_email_is_admin
# ---------------------------------------------------------------------------


class TestCsvSet:
    """Line 307: csv_set."""

    def test_csv_set(self):
        from shared.auth_core import csv_set

        result = csv_set("Alice@Example.COM, bob@test.org, ")
        assert result == {"alice@example.com", "bob@test.org"}


class TestOAuthEmailAllowed:
    """Lines 312-320: oauth_email_allowed."""

    def test_no_restrictions(self):
        from shared.auth_core import oauth_email_allowed

        settings = MagicMock()
        settings.ENV = "dev"
        settings.OAUTH_ALLOWED_EMAILS = ""
        settings.OAUTH_ALLOWED_DOMAINS = ""
        with patch("shared.auth_core.settings", settings, create=True):
            with patch("config.settings", settings):
                assert oauth_email_allowed("anyone@test.com") is True

    def test_email_in_allowlist(self):
        from shared.auth_core import oauth_email_allowed

        settings = MagicMock()
        settings.OAUTH_ALLOWED_EMAILS = "admin@test.com"
        settings.OAUTH_ALLOWED_DOMAINS = ""
        with patch("config.settings", settings):
            assert oauth_email_allowed("admin@test.com") is True

    def test_domain_in_allowlist(self):
        from shared.auth_core import oauth_email_allowed

        settings = MagicMock()
        settings.OAUTH_ALLOWED_EMAILS = ""
        settings.OAUTH_ALLOWED_DOMAINS = "allowed.com"
        with patch("config.settings", settings):
            assert oauth_email_allowed("user@allowed.com") is True

    def test_email_not_allowed(self):
        from shared.auth_core import oauth_email_allowed

        settings = MagicMock()
        settings.OAUTH_ALLOWED_EMAILS = "other@test.com"
        settings.OAUTH_ALLOWED_DOMAINS = "other.com"
        with patch("config.settings", settings):
            assert oauth_email_allowed("user@bad.com") is False


class TestOAuthEmailIsAdmin:
    """Lines 325-327: oauth_email_is_admin."""

    def test_admin_true(self):
        from shared.auth_core import oauth_email_is_admin

        settings = MagicMock()
        settings.OAUTH_ADMIN_EMAILS = "admin@test.com,boss@test.com"
        with patch("config.settings", settings):
            assert oauth_email_is_admin("Admin@Test.COM") is True

    def test_admin_false(self):
        from shared.auth_core import oauth_email_is_admin

        settings = MagicMock()
        settings.OAUTH_ADMIN_EMAILS = "admin@test.com"
        with patch("config.settings", settings):
            assert oauth_email_is_admin("user@test.com") is False


# ---------------------------------------------------------------------------
# PKCE — generate_pkce_pair / verify_pkce
# ---------------------------------------------------------------------------


class TestPKCE:
    """Lines 351-355, 364-368: generate_pkce_pair and verify_pkce."""

    def test_generate_pkce_pair(self):
        from shared.auth_core import generate_pkce_pair

        verifier, challenge = generate_pkce_pair()
        assert isinstance(verifier, str)
        assert isinstance(challenge, str)
        assert len(verifier) > 10
        assert len(challenge) > 10

    def test_verify_pkce_valid(self):
        from shared.auth_core import generate_pkce_pair, verify_pkce

        verifier, challenge = generate_pkce_pair()
        assert verify_pkce(verifier, challenge) is True

    def test_verify_pkce_invalid(self):
        from shared.auth_core import verify_pkce

        assert verify_pkce("wrong_verifier", "wrong_challenge") is False

    def test_verify_pkce_empty(self):
        from shared.auth_core import verify_pkce

        assert verify_pkce("", "challenge") is False
        assert verify_pkce("verifier", "") is False


# ---------------------------------------------------------------------------
# validate_google_id_token — claim validation branches
# ---------------------------------------------------------------------------


class TestValidateGoogleIdToken:
    """Lines 403-440: validate_google_id_token."""

    def test_empty_claims(self):
        from shared.auth_core import validate_google_id_token

        assert validate_google_id_token({}, audience="aud") is False
        assert validate_google_id_token(None, audience="aud") is False

    def test_invalid_iss(self):
        from shared.auth_core import validate_google_id_token

        claims = {"iss": "evil.com", "aud": "aud", "exp": int(time.time()) + 600}
        assert validate_google_id_token(claims, audience="aud") is False

    def test_invalid_aud(self):
        from shared.auth_core import validate_google_id_token

        claims = {"iss": "accounts.google.com", "aud": "wrong", "exp": int(time.time()) + 600}
        assert validate_google_id_token(claims, audience="myapp") is False

    def test_missing_exp(self):
        from shared.auth_core import validate_google_id_token

        claims = {"iss": "accounts.google.com", "aud": "myapp"}
        assert validate_google_id_token(claims, audience="myapp") is False

    def test_expired_token(self):
        from shared.auth_core import validate_google_id_token

        claims = {"iss": "accounts.google.com", "aud": "myapp", "exp": int(time.time()) - 600}
        assert validate_google_id_token(claims, audience="myapp") is False

    def test_invalid_exp_format(self):
        from shared.auth_core import validate_google_id_token

        claims = {"iss": "accounts.google.com", "aud": "myapp", "exp": "not_a_number"}
        assert validate_google_id_token(claims, audience="myapp") is False

    def test_email_not_verified(self):
        from shared.auth_core import validate_google_id_token

        claims = {
            "iss": "accounts.google.com",
            "aud": "myapp",
            "exp": int(time.time()) + 600,
            "email_verified": False,
        }
        assert validate_google_id_token(claims, audience="myapp") is False

    def test_valid_token(self):
        from shared.auth_core import validate_google_id_token

        claims = {
            "iss": "accounts.google.com",
            "aud": "myapp",
            "sub": "google-subject-123",
            "exp": int(time.time()) + 600,
            "email_verified": True,
        }
        assert validate_google_id_token(claims, audience="myapp") is True

    def test_valid_token_no_email_verify_required(self):
        from shared.auth_core import validate_google_id_token

        claims = {
            "iss": "https://accounts.google.com",
            "aud": "myapp",
            "sub": "google-subject-123",
            "exp": int(time.time()) + 600,
            "email_verified": False,
        }
        assert (
            validate_google_id_token(claims, audience="myapp", require_email_verified=False) is True
        )

    def test_aud_as_list(self):
        from shared.auth_core import validate_google_id_token

        claims = {
            "iss": "accounts.google.com",
            "aud": ["myapp", "other"],
            "azp": "myapp",
            "sub": "google-subject-123",
            "exp": int(time.time()) + 600,
            "email_verified": True,
        }
        assert validate_google_id_token(claims, audience="myapp") is True
