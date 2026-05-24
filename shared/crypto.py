"""Criptografía compartida: derivación de secretos de webhook + cifrado TOTP.

Webhook secrets (issue #49):
    En lugar de almacenar secretos en texto plano en la BD, derivamos la clave
    de firma de cada webhook a partir de una clave maestra del servidor:

        signing_key = HMAC-SHA256(master_key, "webhook-v1:{webhook_id}")

    El secreto derivado se devuelve al usuario una sola vez en la creación.
    En cada entrega, se re-deriva desde la master key + webhook_id.

TOTP encryption (issue #43):
    Usa Fernet (AES-128-CBC + HMAC-SHA256) de la librería ``cryptography``.
    La clave se lee de ``TOTP_ENCRYPTION_KEY`` (env var / settings).

    En modo dev (sin clave configurada) se genera una clave efímera con warning.
    En producción la clave es **obligatoria**.

    Generar una clave válida::

        python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import warnings
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from observability.logging import get_logger

log = get_logger(__name__)

# ── Webhook secret derivation ────────────────────────────────────────────

_DERIVATION_PREFIX = "webhook-v1"

# Sentinel value stored in DB instead of the real secret.
DERIVED_SECRET_SENTINEL = "derived:v1"  # noqa: S105  # pragma: allowlist secret


def derive_webhook_secret(master_key: str, webhook_id: int) -> str:
    """Derive a per-webhook signing key from the server master key.

    Returns a URL-safe base64 string suitable for HMAC signing.
    """
    if not master_key:
        raise ValueError("master_key must not be empty")
    context = f"{_DERIVATION_PREFIX}:{webhook_id}".encode()
    derived = hmac.new(
        master_key.encode("utf-8"),
        context,
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(derived).rstrip(b"=").decode("ascii")


def is_derived_secret(secret: str) -> bool:
    """Check whether a stored secret is the derivation sentinel."""
    return secret.startswith("derived:")


# ── TOTP encryption ─────────────────────────────────────────────────────


class TOTPDecryptionError(Exception):
    """No se pudo descifrar un secreto TOTP."""


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Devuelve una instancia Fernet cacheada.

    Lee ``TOTP_ENCRYPTION_KEY`` del entorno. Si no está configurada,
    genera una clave efímera (solo válida para la sesión actual).
    """
    key = os.getenv("TOTP_ENCRYPTION_KEY", "").strip()
    if not key:
        env = os.getenv("ENV", "dev")
        if env == "prod":
            msg = (
                "TOTP_ENCRYPTION_KEY no configurada en producción. "
                "Los secretos TOTP no se pueden cifrar de forma segura."
            )
            raise RuntimeError(msg)
        # Dev/staging: clave efímera con warning
        ephemeral = Fernet.generate_key()
        warnings.warn(
            "TOTP_ENCRYPTION_KEY no configurada — usando clave efímera. "
            "Los secretos cifrados NO sobrevivirán un reinicio.",
            UserWarning,
            stacklevel=2,
        )
        log.warning("totp_encryption_using_ephemeral_key")
        return Fernet(ephemeral)

    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        msg = f"TOTP_ENCRYPTION_KEY inválida: {exc}"
        raise RuntimeError(msg) from exc


def reload_encryption_key() -> None:
    """Invalida el caché de la clave. Re-leerá del entorno en el siguiente uso."""
    _get_fernet.cache_clear()


def encrypt_totp_secret(plaintext: str) -> str:
    """Cifra un secreto TOTP y devuelve el ciphertext como string base64 URL-safe.

    Args:
        plaintext: El secreto TOTP en texto plano (base32).

    Returns:
        Ciphertext Fernet (base64 URL-safe).
    """
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_totp_secret(ciphertext: str) -> str:
    """Descifra un secreto TOTP cifrado con Fernet.

    Args:
        ciphertext: El token Fernet (base64 URL-safe).

    Returns:
        El secreto TOTP en texto plano.

    Raises:
        TOTPDecryptionError: Si el ciphertext es inválido o la clave no coincide.
    """
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        msg = "No se pudo descifrar el secreto TOTP — clave incorrecta o dato corrupto"
        raise TOTPDecryptionError(msg) from exc


def is_encrypted(value: str) -> bool:
    """Heurística: detecta si un valor ya está cifrado con Fernet.

    Los tokens Fernet empiezan con ``gAAAAA`` (version byte 0x80 en base64).
    Los secretos TOTP base32 nunca empiezan así.
    """
    return value.startswith("gAAAAA")


__all__ = [
    "DERIVED_SECRET_SENTINEL",
    "TOTPDecryptionError",
    "decrypt_totp_secret",
    "derive_webhook_secret",
    "encrypt_totp_secret",
    "is_derived_secret",
    "is_encrypted",
    "reload_encryption_key",
]
