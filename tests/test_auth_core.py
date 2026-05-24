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
    store.add("abc")
    store._client.set.assert_called_once()
    store._client.exists.return_value = 1
    assert store.contains("abc")


def _make_redis_store_with_mock():
    """Crea un _RedisNonceStore con cliente Redis mockeado."""
    from shared.auth_core import _RedisNonceStore

    store = _RedisNonceStore.__new__(_RedisNonceStore)
    store._prefix = "oauth_nonce:"
    store._client = MagicMock()
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


def test_redis_nonce_store_contains_fail_open():
    """Si Redis lanza excepción, contains() devuelve False (fail-open)."""
    store = _make_redis_store_with_mock()
    store._client.exists.side_effect = ConnectionError("Redis down")
    assert not store.contains("nonce123")


def test_redis_nonce_store_add_fail_silent():
    """Si Redis lanza excepción en add(), no propaga."""
    store = _make_redis_store_with_mock()
    store._client.set.side_effect = ConnectionError("Redis down")
    store.add("nonce_xyz", 600)  # no debe lanzar


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
