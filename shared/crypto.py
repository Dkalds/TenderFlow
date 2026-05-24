"""Cifrado simétrico para secretos TOTP at-rest.

Usa Fernet (AES-128-CBC + HMAC-SHA256) de la librería ``cryptography``.
La clave se lee de ``TOTP_ENCRYPTION_KEY`` (env var / settings).

En modo dev (sin clave configurada) se genera una clave efímera con warning.
En producción la clave es **obligatoria**.

Generar una clave válida::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import os
import warnings
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from observability.logging import get_logger

log = get_logger(__name__)


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
    "TOTPDecryptionError",
    "decrypt_totp_secret",
    "encrypt_totp_secret",
    "is_encrypted",
    "reload_encryption_key",
]
