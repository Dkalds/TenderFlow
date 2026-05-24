"""Tests para shared/crypto.py — derivación de secretos de webhook."""

from __future__ import annotations

import pytest

from shared.crypto import (
    DERIVED_SECRET_SENTINEL,
    derive_webhook_secret,
    is_derived_secret,
)


class TestDeriveWebhookSecret:
    def test_deterministic(self):
        """Same inputs produce same output."""
        key = "test-master-key-32chars-long!!!!!"  # pragma: allowlist secret
        s1 = derive_webhook_secret(key, 1)
        s2 = derive_webhook_secret(key, 1)
        assert s1 == s2

    def test_different_ids_produce_different_secrets(self):
        key = "test-master-key-32chars-long!!!!!"  # pragma: allowlist secret
        s1 = derive_webhook_secret(key, 1)
        s2 = derive_webhook_secret(key, 2)
        assert s1 != s2

    def test_different_keys_produce_different_secrets(self):
        s1 = derive_webhook_secret("key-a-long-enough-for-test!!!!!!!", 1)
        s2 = derive_webhook_secret("key-b-long-enough-for-test!!!!!!!", 1)
        assert s1 != s2

    def test_returns_url_safe_string(self):
        key = "test-master-key-32chars-long!!!!!"  # pragma: allowlist secret
        secret = derive_webhook_secret(key, 42)
        # URL-safe base64 only contains these chars
        import re
        assert re.match(r'^[A-Za-z0-9_-]+$', secret)

    def test_empty_key_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            derive_webhook_secret("", 1)


class TestIsDerivedSecret:
    def test_sentinel_detected(self):
        assert is_derived_secret(DERIVED_SECRET_SENTINEL) is True

    def test_random_secret_not_detected(self):
        assert is_derived_secret("abc123random") is False

    def test_derived_prefix_detected(self):
        assert is_derived_secret("derived:v2") is True


class TestSentinel:
    def test_sentinel_value(self):
        assert DERIVED_SECRET_SENTINEL == "derived:v1"
