"""Tests para db/totp.py — TOTP secrets, verificación y recovery codes."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Configura una clave Fernet válida para todos los tests de TOTP."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", key)
    from shared.crypto import reload_encryption_key

    reload_encryption_key()
    yield
    reload_encryption_key()


# ---------------------------------------------------------------------------
# generate_totp_secret
# ---------------------------------------------------------------------------


def test_generate_totp_secret_returns_base32(tmp_db):
    _, _ = tmp_db
    from db.totp import generate_totp_secret

    secret = generate_totp_secret()
    assert isinstance(secret, str)
    assert len(secret) >= 16


# ---------------------------------------------------------------------------
# get_totp_uri
# ---------------------------------------------------------------------------


def test_get_totp_uri_format(tmp_db):
    _, _ = tmp_db
    from db.totp import get_totp_uri

    uri = get_totp_uri("JBSWY3DPEHPK3PXP", "user@test.com")
    assert uri.startswith("otpauth://totp/")
    assert "JBSWY3DPEHPK3PXP" in uri
    assert "user%40test.com" in uri or "user@test.com" in uri


# ---------------------------------------------------------------------------
# save / get / confirm / delete totp_secret
# ---------------------------------------------------------------------------


def test_save_and_get_totp_secret(tmp_db):
    _, _ = tmp_db
    from db.totp import get_totp_secret, save_totp_secret

    save_totp_secret(1, "MYSECRET", confirmed=False)
    result = get_totp_secret(1)
    assert result is not None
    assert result["secret"] == "MYSECRET"  # pragma: allowlist secret
    assert result["confirmed"] is False


def test_secret_stored_encrypted_in_db(tmp_db):
    """Verifica que el secreto se almacena cifrado en la BD, no en texto plano."""
    _, _ = tmp_db
    from db.totp import save_totp_secret

    save_totp_secret(1, "PLAINTEXT_SECRET")

    from db.database import connect

    with connect() as c:
        row = c.execute("SELECT secret FROM totp_secrets WHERE user_id = %s", (1,)).fetchone()
    assert row is not None
    raw_value = row[0]
    assert raw_value != "PLAINTEXT_SECRET"  # pragma: allowlist secret
    assert raw_value.startswith("gAAAAA")  # Fernet prefix


def test_confirm_totp(tmp_db):
    _, _ = tmp_db
    from db.totp import confirm_totp, get_totp_secret, save_totp_secret

    save_totp_secret(1, "SEC123")
    confirm_totp(1)
    result = get_totp_secret(1)
    assert result is not None
    assert result["confirmed"] is True


def test_delete_totp(tmp_db):
    _, _ = tmp_db
    from db.totp import delete_totp, get_totp_secret, save_totp_secret

    save_totp_secret(1, "DELSEC")
    delete_totp(1)
    assert get_totp_secret(1) is None


def test_get_totp_secret_none_when_missing(tmp_db):
    _, _ = tmp_db
    from db.totp import get_totp_secret

    assert get_totp_secret(999) is None


# ---------------------------------------------------------------------------
# is_totp_required
# ---------------------------------------------------------------------------


def test_is_totp_required_false_when_unconfirmed(tmp_db):
    _, _ = tmp_db
    from db.totp import is_totp_required, save_totp_secret

    save_totp_secret(1, "UNCONF")
    assert is_totp_required(1) is False


def test_is_totp_required_true_when_confirmed(tmp_db):
    _, _ = tmp_db
    from db.totp import confirm_totp, is_totp_required, save_totp_secret

    save_totp_secret(1, "CONF")
    confirm_totp(1)
    assert is_totp_required(1) is True


# ---------------------------------------------------------------------------
# recovery codes
# ---------------------------------------------------------------------------


def test_generate_recovery_codes_returns_10(tmp_db):
    _, _ = tmp_db
    from db.totp import generate_recovery_codes

    codes = generate_recovery_codes(1)
    assert len(codes) == 10
    assert all(isinstance(c, str) and len(c) == 16 for c in codes)  # hex(8) = 16 chars


def test_use_recovery_code_valid(tmp_db):
    _, _ = tmp_db
    from db.totp import generate_recovery_codes, use_recovery_code

    codes = generate_recovery_codes(1)
    assert use_recovery_code(1, codes[0]) is True
    # Same code should not work again
    assert use_recovery_code(1, codes[0]) is False


def test_use_recovery_code_invalid(tmp_db):
    _, _ = tmp_db
    from db.totp import generate_recovery_codes, use_recovery_code

    generate_recovery_codes(1)
    assert use_recovery_code(1, "totally_wrong_code") is False


def test_save_totp_upsert_overwrites(tmp_db):
    _, _ = tmp_db
    from db.totp import get_totp_secret, save_totp_secret

    save_totp_secret(1, "FIRST")
    save_totp_secret(1, "SECOND", confirmed=True)
    result = get_totp_secret(1)
    assert result is not None
    assert result["secret"] == "SECOND"  # pragma: allowlist secret
    assert result["confirmed"] is True


# ---------------------------------------------------------------------------
# backward compatibility — legacy unencrypted secrets
# ---------------------------------------------------------------------------


def test_get_totp_secret_reads_legacy_plaintext(tmp_db):
    """Secretos legacy (sin cifrar) se leen correctamente."""
    _, _ = tmp_db
    from db.database import connect, now_utc_iso
    from db.totp import get_totp_secret

    # Insertar directamente sin cifrar (simula dato legacy)
    with connect() as c:
        c.execute(
            "INSERT INTO totp_secrets (user_id, secret, confirmed, created_at) VALUES (%s, %s, %s, %s)",
            (99, "LEGACY_PLAIN_SECRET", 1, now_utc_iso()),
        )

    result = get_totp_secret(99)
    assert result is not None
    assert result["secret"] == "LEGACY_PLAIN_SECRET"  # pragma: allowlist secret
    assert result["confirmed"] is True
