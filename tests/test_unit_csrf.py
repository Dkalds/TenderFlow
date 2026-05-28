"""Unit tests for shared.csrf — HMAC-signed CSRF token generation & validation."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from shared.csrf import generate_csrf_token, validate_csrf_token


@pytest.fixture(autouse=True)
def _set_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a deterministic signing key for all tests."""
    monkeypatch.setenv("SIGNING_KEY", "test-csrf-secret-key-1234")
    # Clear the lru_cache so the new env var is picked up
    from shared.signing import reload_keys

    reload_keys()


class TestGenerateCsrfToken:
    def test_returns_string_with_three_parts(self) -> None:
        token = generate_csrf_token("session-abc")
        parts = token.split(":", 2)
        assert len(parts) == 3, f"Expected 3 colon-separated parts, got {len(parts)}"

    def test_session_hash_is_deterministic(self) -> None:
        t1 = generate_csrf_token("session-abc")
        t2 = generate_csrf_token("session-abc")
        # Same session → same hash prefix
        assert t1.split(":")[0] == t2.split(":")[0]

    def test_different_sessions_produce_different_hashes(self) -> None:
        t1 = generate_csrf_token("session-abc")
        t2 = generate_csrf_token("session-xyz")
        assert t1.split(":")[0] != t2.split(":")[0]

    def test_empty_session_raises(self) -> None:
        with pytest.raises(ValueError, match="session_id must not be empty"):
            generate_csrf_token("")


class TestValidateCsrfToken:
    def test_valid_token(self) -> None:
        session = "my-session-id"
        token = generate_csrf_token(session)
        assert validate_csrf_token(token, session) is True

    def test_wrong_session_rejected(self) -> None:
        token = generate_csrf_token("session-a")
        assert validate_csrf_token(token, "session-b") is False

    def test_expired_token_rejected(self) -> None:
        session = "sess"
        token = generate_csrf_token(session)
        # Simulate time passing beyond max_age
        with patch("shared.csrf.time") as mock_time:
            mock_time.time.return_value = time.time() + 7200
            assert validate_csrf_token(token, session, max_age=3600) is False

    def test_tampered_signature_rejected(self) -> None:
        session = "sess"
        token = generate_csrf_token(session)
        parts = token.split(":", 2)
        sig = parts[2]
        # Flip a char in the middle of the signature (avoid last char which
        # may only differ in base64 padding bits for 32-byte HMAC-SHA256).
        mid = len(sig) // 2
        flipped = chr(ord(sig[mid]) ^ 0x01)
        parts[2] = sig[:mid] + flipped + sig[mid + 1 :]
        tampered = ":".join(parts)
        assert validate_csrf_token(tampered, session) is False

    def test_tampered_timestamp_rejected(self) -> None:
        session = "sess"
        token = generate_csrf_token(session)
        parts = token.split(":", 2)
        # Change timestamp
        parts[1] = str(int(parts[1]) + 1)
        tampered = ":".join(parts)
        assert validate_csrf_token(tampered, session) is False

    def test_empty_token_rejected(self) -> None:
        assert validate_csrf_token("", "sess") is False

    def test_empty_session_rejected(self) -> None:
        assert validate_csrf_token("some:token:here", "") is False

    def test_malformed_token_rejected(self) -> None:
        assert validate_csrf_token("no-colons-here", "sess") is False
        assert validate_csrf_token("only:one", "sess") is False

    def test_custom_max_age(self) -> None:
        session = "sess"
        token = generate_csrf_token(session)
        # With very short max_age and slight time shift, should still pass
        assert validate_csrf_token(token, session, max_age=10) is True

    def test_non_numeric_timestamp_rejected(self) -> None:
        session = "sess"
        token = generate_csrf_token(session)
        parts = token.split(":", 2)
        parts[1] = "not-a-number"
        tampered = ":".join(parts)
        assert validate_csrf_token(tampered, session) is False
