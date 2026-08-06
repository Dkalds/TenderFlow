"""CRUD para 2FA TOTP — generación de secrets, verificación y recovery codes."""

from __future__ import annotations

import os
import secrets
from typing import Any

from argon2 import PasswordHasher

from db.database import connect, now_utc_iso
from shared.crypto import (
    TOTPDecryptionError,
    decrypt_totp_secret,
    encrypt_totp_secret,
    is_encrypted,
)

_ph = PasswordHasher()


# ---------------------------------------------------------------------------
# TOTP secret management
# ---------------------------------------------------------------------------


def generate_totp_secret() -> str:
    """Genera un secret TOTP base32 compatible con Google Authenticator."""
    try:
        import pyotp  # type: ignore[import-not-found]

        return str(pyotp.random_base32())
    except ImportError:
        # Fallback: generate 20 random bytes encoded as base32
        import base64

        raw = os.urandom(20)
        return base64.b32encode(raw).decode().rstrip("=")


def get_totp_uri(secret: str, email: str, issuer: str = "Licitaciones-SAP") -> str:
    """Genera el URI otpauth:// para codificar como QR."""
    try:
        import pyotp

        totp = pyotp.TOTP(secret)
        return str(totp.provisioning_uri(name=email, issuer_name=issuer))
    except ImportError:
        from urllib.parse import quote

        return (
            f"otpauth://totp/{quote(issuer)}:{quote(email)}"
            f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
        )


def verify_totp(secret: str, code: str) -> bool:
    """Verifica un código TOTP (ventana de ±1 período = 90s tolerancia)."""
    if not secret or not code:
        return False
    try:
        import pyotp

        totp = pyotp.TOTP(secret)
        return bool(totp.verify(code, valid_window=1))
    except ImportError:
        # RFC 6238 fallback: the optional ``pyotp`` dependency must not make
        # MFA unusable in a minimal deployment.
        import base64
        import hashlib
        import hmac
        import time

        if len(code) != 6 or not code.isdecimal():
            return False
        try:
            key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8), casefold=True)
        except Exception:
            return False
        counter = int(time.time() // 30)
        for candidate in (counter - 1, counter, counter + 1):
            digest = hmac.new(key, candidate.to_bytes(8, "big"), hashlib.sha1).digest()
            offset = digest[-1] & 0x0F
            value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFF_FFFF
            expected = f"{value % 1_000_000:06d}"
            if hmac.compare_digest(expected, code):
                return True
        return False


# ---------------------------------------------------------------------------
# DB operations — totp_secrets table
# ---------------------------------------------------------------------------


def save_totp_secret(user_id: int, secret: str, *, confirmed: bool = False) -> None:
    """Guarda o actualiza el TOTP secret del usuario (cifrado at-rest)."""
    encrypted = encrypt_totp_secret(secret)
    with connect() as c:
        c.execute(
            "INSERT INTO totp_secrets (user_id, secret, confirmed, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET secret=excluded.secret, "
            "confirmed=excluded.confirmed",
            (user_id, encrypted, 1 if confirmed else 0, now_utc_iso()),
        )


def confirm_totp(user_id: int) -> None:
    """Marca el TOTP como confirmado (tras primer uso exitoso)."""
    with connect() as c:
        c.execute("UPDATE totp_secrets SET confirmed = 1 WHERE user_id = ?", (user_id,))


def get_totp_secret(user_id: int) -> dict[str, Any] | None:
    """Devuelve {secret, confirmed} o None si no tiene TOTP configurado.

    El secreto se descifra transparentemente. Si el valor almacenado no está
    cifrado (legacy), se devuelve tal cual para compatibilidad hacia atrás.
    """
    with connect() as c:
        row = c.execute(
            "SELECT secret, confirmed FROM totp_secrets WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row is None:
        return None

    raw_secret: str = row[0]
    if is_encrypted(raw_secret):
        try:
            plaintext = decrypt_totp_secret(raw_secret)
        except TOTPDecryptionError:
            # Log pero no crashear — devolver None para forzar re-setup
            from observability.logging import get_logger

            get_logger(__name__).error("totp_decryption_failed", user_id=user_id)
            return None
    else:
        # Legacy: secreto sin cifrar — compatibilidad hacia atrás
        plaintext = raw_secret

    return {"secret": plaintext, "confirmed": bool(row[1])}


def delete_totp(user_id: int) -> None:
    """Elimina el TOTP del usuario (reset)."""
    with connect() as c:
        c.execute("DELETE FROM totp_secrets WHERE user_id = ?", (user_id,))
        c.execute("DELETE FROM totp_recovery_codes WHERE user_id = ?", (user_id,))


def is_totp_required(user_id: int) -> bool:
    """True si el usuario tiene TOTP confirmado (requiere verificación en login)."""
    rec = get_totp_secret(user_id)
    return rec is not None and rec["confirmed"]


# ---------------------------------------------------------------------------
# Recovery codes
# ---------------------------------------------------------------------------

_N_RECOVERY = 10


def generate_recovery_codes(user_id: int) -> list[str]:
    """Genera N recovery codes, los hashea con argon2 y guarda en DB.

    Devuelve los códigos en texto plano (mostrar UNA sola vez al usuario).
    """
    codes_plain = [secrets.token_hex(8) for _ in range(_N_RECOVERY)]
    with connect() as c:
        c.execute("DELETE FROM totp_recovery_codes WHERE user_id = ?", (user_id,))
        for code in codes_plain:
            hashed = _ph.hash(code)
            c.execute(
                "INSERT INTO totp_recovery_codes (user_id, code_hash, used, created_at) "
                "VALUES (?, ?, 0, ?)",
                (user_id, hashed, now_utc_iso()),
            )
    return codes_plain


def use_recovery_code(user_id: int, code: str) -> bool:
    """Verifica y consume un recovery code. Devuelve True si válido."""
    with connect() as c:
        rows = c.execute(
            "SELECT id, code_hash FROM totp_recovery_codes WHERE user_id = ? AND used = 0",
            (user_id,),
        ).fetchall()
        for row_id, code_hash in rows:
            try:
                if _ph.verify(code_hash, code):
                    # Consumo atómico: el ``AND used = 0`` + ``rowcount`` cierra la
                    # carrera de dos requests concurrentes con el mismo código. Ambas
                    # pasan el SELECT y verifican argon2, pero el lock de fila de
                    # Postgres serializa los UPDATE: solo el primero marca la fila
                    # (rowcount == 1); el segundo re-evalúa el WHERE sobre la fila ya
                    # commiteada (used = 1) y matchea 0 filas → no es un consumo válido.
                    consumed: int = c.execute(
                        "UPDATE totp_recovery_codes SET used = 1, used_at = ? "
                        "WHERE id = ? AND used = 0",
                        (now_utc_iso(), row_id),
                    ).rowcount
                    return consumed == 1
            except Exception:  # noqa: S112
                continue
    return False
