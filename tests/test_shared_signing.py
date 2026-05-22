"""Tests para shared/signing.py — HMAC sign/verify con kid rotation."""

from __future__ import annotations

import os
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def reload_signing():
    """Recarga el módulo y limpia lru_cache."""
    from shared import signing

    signing.reload_keys()
    return signing


# ---------------------------------------------------------------------------
# sign / verify básico
# ---------------------------------------------------------------------------


def test_sign_returns_string():
    from shared.signing import sign

    token = sign(b"payload")
    assert isinstance(token, str)
    assert "." in token


def test_verify_valid_signature():
    from shared.signing import reload_keys, sign, verify

    reload_keys()
    payload = b"test-payload-123"
    token = sign(payload)
    assert verify(payload, token) is True


def test_verify_wrong_payload():
    from shared.signing import reload_keys, sign, verify

    reload_keys()
    token = sign(b"original")
    assert verify(b"tampered", token) is False


def test_verify_empty_token():
    from shared.signing import verify

    assert verify(b"data", "") is False


def test_verify_malformed_token_no_dot():
    from shared.signing import verify

    assert verify(b"data", "nodothere") is False


def test_verify_unknown_kid():
    from shared.signing import verify

    assert verify(b"data", "unknownkid.AAAA") is False


# ---------------------------------------------------------------------------
# dev ephemeral key (no SIGNING_KEY set)
# ---------------------------------------------------------------------------


def test_dev_mode_works_without_signing_key():
    """En modo dev sin SIGNING_KEY, se usa clave efímera y sign+verify funciona."""
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("SIGNING_KEY", "SIGNING_KEYS_JSON", "SIGNING_KEY_ACTIVE")
    }
    with patch.dict(os.environ, env, clear=True):
        from shared import signing

        signing.reload_keys()
        token = signing.sign(b"data")
        assert signing.verify(b"data", token) is True
        signing.reload_keys()


# ---------------------------------------------------------------------------
# Multi-key rotation
# ---------------------------------------------------------------------------


def test_multi_key_rotation():
    """Firma con k1, verifica que sigue funcionando tras añadir k2."""
    import base64
    import json
    import os

    k1 = base64.urlsafe_b64encode(b"k" * 32).decode()
    k2 = base64.urlsafe_b64encode(b"m" * 32).decode()
    keys_json = json.dumps({"k1": k1, "k2": k2})

    with patch.dict(
        os.environ,
        {
            "SIGNING_KEYS_JSON": keys_json,
            "SIGNING_KEY_ACTIVE": "k1",
        },
        clear=False,
    ):
        from shared import signing

        signing.reload_keys()
        token = signing.sign(b"payload")
        assert token.startswith("k1.")
        assert signing.verify(b"payload", token) is True

    # Rotar a k2 — k1 sigue siendo verificable
    with patch.dict(
        os.environ,
        {
            "SIGNING_KEYS_JSON": keys_json,
            "SIGNING_KEY_ACTIVE": "k2",
        },
        clear=False,
    ):
        signing.reload_keys()
        new_token = signing.sign(b"payload")
        assert new_token.startswith("k2.")
        # Token antiguo (k1) aún válido
        assert signing.verify(b"payload", token) is True
        # Token nuevo (k2) también válido
        assert signing.verify(b"payload", new_token) is True
        signing.reload_keys()


def test_reload_keys_clears_cache():
    from shared.signing import _load_keys, reload_keys

    reload_keys()
    first = _load_keys()
    reload_keys()
    second = _load_keys()
    # Debe producir el mismo resultado (mismo entorno), pero limpiar cache
    assert first[1] == second[1]


def test_active_kid_returns_string():
    from shared.signing import active_kid, reload_keys

    reload_keys()
    kid = active_kid()
    assert isinstance(kid, str)
    assert len(kid) > 0


def test_known_kids_includes_active():
    from shared.signing import active_kid, known_kids, reload_keys

    reload_keys()
    assert active_kid() in known_kids()


# ---------------------------------------------------------------------------
# Legacy SIGNING_KEY
# ---------------------------------------------------------------------------


def test_legacy_signing_key():
    env = {
        k: v for k, v in os.environ.items() if k not in ("SIGNING_KEYS_JSON", "SIGNING_KEY_ACTIVE")
    }
    env["SIGNING_KEY"] = "legacy-secret-key-for-testing-purposes"
    with patch.dict(os.environ, env, clear=True):
        from shared import signing

        signing.reload_keys()
        token = signing.sign(b"test")
        assert token.startswith("legacy.")
        assert signing.verify(b"test", token) is True
        signing.reload_keys()
