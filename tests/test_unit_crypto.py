"""Tests unitarios para shared/crypto.py — cifrado de secretos TOTP."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Configura una clave Fernet válida para todos los tests."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", key)
    # Limpiar caché entre tests
    from shared.crypto import reload_encryption_key

    reload_encryption_key()
    yield
    reload_encryption_key()


def test_encrypt_decrypt_roundtrip():
    from shared.crypto import decrypt_totp_secret, encrypt_totp_secret

    secret = "JBSWY3DPEHPK3PXP"
    encrypted = encrypt_totp_secret(secret)
    assert encrypted != secret
    assert decrypt_totp_secret(encrypted) == secret


def test_encrypted_starts_with_fernet_prefix():
    from shared.crypto import encrypt_totp_secret, is_encrypted

    encrypted = encrypt_totp_secret("MYSECRET")
    assert is_encrypted(encrypted)


def test_plaintext_not_detected_as_encrypted():
    from shared.crypto import is_encrypted

    assert not is_encrypted("JBSWY3DPEHPK3PXP")
    assert not is_encrypted("")


def test_decrypt_invalid_token_raises():
    from shared.crypto import TOTPDecryptionError, decrypt_totp_secret

    with pytest.raises(TOTPDecryptionError):
        decrypt_totp_secret("not-a-valid-fernet-token")


def test_decrypt_wrong_key_raises(monkeypatch):
    from shared.crypto import encrypt_totp_secret, reload_encryption_key

    encrypted = encrypt_totp_secret("SECRET123")

    # Cambiar a otra clave
    new_key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", new_key)
    reload_encryption_key()

    from shared.crypto import TOTPDecryptionError, decrypt_totp_secret

    with pytest.raises(TOTPDecryptionError):
        decrypt_totp_secret(encrypted)


def test_ephemeral_key_in_dev(monkeypatch):
    from shared.crypto import reload_encryption_key

    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", "")
    monkeypatch.setenv("ENV", "dev")
    reload_encryption_key()

    from shared.crypto import decrypt_totp_secret, encrypt_totp_secret

    with pytest.warns(UserWarning, match="clave efímera"):
        encrypted = encrypt_totp_secret("TESTSECRET")
    assert decrypt_totp_secret(encrypted) == "TESTSECRET"


def test_prod_without_key_raises(monkeypatch):
    from shared.crypto import reload_encryption_key

    monkeypatch.setenv("TOTP_ENCRYPTION_KEY", "")
    monkeypatch.setenv("ENV", "prod")
    reload_encryption_key()

    from shared.crypto import encrypt_totp_secret

    with pytest.raises(RuntimeError, match="TOTP_ENCRYPTION_KEY no configurada"):
        encrypt_totp_secret("FAIL")


def test_multiple_encryptions_produce_different_ciphertexts():
    """Fernet incluye timestamp + IV, así que cada cifrado es único."""
    from shared.crypto import encrypt_totp_secret

    secret = "SAMESECRET"
    e1 = encrypt_totp_secret(secret)
    e2 = encrypt_totp_secret(secret)
    assert e1 != e2  # Diferentes por IV/timestamp
