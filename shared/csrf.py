"""CSRF token generation and validation — HMAC-signed, session-bound.

Generates stateless CSRF tokens tied to a specific session ID using
HMAC-SHA256 via :mod:`shared.signing`. Supports key rotation transparently.

Token format: ``{session_hash}:{timestamp}:{kid}.{sig}``

* ``session_hash`` — first 16 chars of SHA-256(session_id), avoids leaking
  the raw session token.
* ``timestamp`` — Unix epoch seconds when the token was minted.
* ``kid.sig`` — HMAC signature produced by :func:`shared.signing.sign`.

Usage::

    from shared.csrf import generate_csrf_token, validate_csrf_token

    token = generate_csrf_token(session_id)
    is_valid = validate_csrf_token(token, session_id, max_age=3600)
"""

from __future__ import annotations

import hashlib
import time

from shared.signing import sign, verify

# Default max age: 1 hour
DEFAULT_MAX_AGE_SECONDS: int = 3600


def _session_hash(session_id: str) -> str:
    """Return a truncated SHA-256 hex digest of *session_id*."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def generate_csrf_token(session_id: str) -> str:
    """Generate an HMAC-signed CSRF token bound to *session_id*.

    Args:
        session_id: The raw session token (cookie value).

    Returns:
        A string ``{session_hash}:{timestamp}:{signature}`` safe for
        embedding in hidden form fields or custom HTTP headers.
    """
    if not session_id:
        raise ValueError("session_id must not be empty")
    s_hash = _session_hash(session_id)
    ts = str(int(time.time()))
    payload = f"{s_hash}:{ts}".encode()
    sig = sign(payload)
    return f"{s_hash}:{ts}:{sig}"


def validate_csrf_token(
    token: str,
    session_id: str,
    *,
    max_age: int = DEFAULT_MAX_AGE_SECONDS,
) -> bool:
    """Validate a CSRF token against *session_id* and freshness.

    Checks:
    1. Token format is correct (3+ colon-separated parts).
    2. Session hash matches the provided *session_id*.
    3. Timestamp is within *max_age* seconds of now.
    4. HMAC signature is valid (via :func:`shared.signing.verify`).

    Args:
        token: The CSRF token string to validate.
        session_id: The raw session token from the cookie.
        max_age: Maximum age in seconds (default 3600).

    Returns:
        ``True`` if the token is valid; ``False`` otherwise.
    """
    if not token or not session_id:
        return False

    # Format: session_hash:timestamp:kid.sig
    # The signature part contains a dot, so we split on ":" with maxsplit=2
    parts = token.split(":", 2)
    if len(parts) != 3:
        return False

    s_hash, ts_str, sig = parts

    # 1. Session binding
    expected_hash = _session_hash(session_id)
    if s_hash != expected_hash:
        return False

    # 2. Freshness
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if abs(time.time() - ts) > max_age:
        return False

    # 3. Signature verification
    payload = f"{s_hash}:{ts_str}".encode()
    return verify(payload, sig)


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "generate_csrf_token",
    "validate_csrf_token",
]
