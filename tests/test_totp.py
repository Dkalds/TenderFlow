"""Tests para db/totp.py — TOTP secrets, verificación y recovery codes."""

from __future__ import annotations

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
