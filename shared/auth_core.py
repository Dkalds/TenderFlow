"""Lógica de autenticación pura — sin dependencias de Streamlit ni de la capa web.

Este módulo centraliza las operaciones criptográficas compartidas entre el
dashboard y la API REST:

* Verificación de contraseñas (argon2/bcrypt)
* Firma y verificación de tokens OAuth state (HMAC-SHA256)
* Validación de emails OAuth contra allowlists

Al no importar ``streamlit``, puede usarse de forma segura en tests unitarios,
tareas del scheduler, y cualquier módulo sin contexto de Streamlit.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from observability.logging import get_logger

log = get_logger(__name__)

# Tiempo máximo de validez del state OAuth (10 minutos)
_OAUTH_STATE_MAX_AGE_SECONDS = 600
_SEEN_OAUTH_NONCES: dict[str, float] = {}


# ---------------------------------------------------------------------------
# Verificación de contraseñas
# ---------------------------------------------------------------------------


def verify_password(candidate: str, pw_hash: str) -> bool:
    """Verifica *candidate* contra *pw_hash*.

    Soporta:
    * **argon2** (``$argon2id$``, ``$argon2i$``, ``$argon2d$``).
    * **bcrypt** (``$2b$``, ``$2y$``, ``$2a$``).

    Returns False y emite warning si el formato no es reconocido o la
    librería correspondiente no está instalada.
    """
    if not pw_hash:
        log.warning(
            "no_password_hash_configured",
            hint="Configura DASHBOARD_PASSWORD_HASH. "
            "Genera el hash con: python scripts/hash_password.py",
        )
        return False

    if pw_hash.startswith("$argon2"):
        try:
            from argon2 import PasswordHasher
            from argon2.exceptions import VerifyMismatchError

            ph = PasswordHasher()
            try:
                return ph.verify(pw_hash, candidate)
            except VerifyMismatchError:
                return False
        except ImportError:
            log.warning("argon2_not_installed", hint="pip install argon2-cffi")
            return False
        except Exception:
            log.warning("argon2_verify_failed", exc_info=True)
            return False

    # bcrypt (prefijo: $2b$, $2y$, $2a$)
    try:
        import bcrypt

        return bcrypt.checkpw(candidate.encode("utf-8"), pw_hash.encode("utf-8"))
    except Exception:
        log.warning("bcrypt_verify_failed", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# OAuth state: HMAC-signed token
# ---------------------------------------------------------------------------


def get_signing_key() -> bytes:
    """Devuelve la clave para firmar/verificar el state OAuth.

    Usa ``SIGNING_KEY`` si está configurada (recomendado en producción).
    Fallback: deriva una clave de ``GOOGLE_CLIENT_SECRET``.
    """
    from config import settings

    if settings.SIGNING_KEY.get_secret_value():
        return settings.SIGNING_KEY.get_secret_value().encode()
    return hashlib.sha256(
        b"oauth_state_signing_v1:" + settings.GOOGLE_CLIENT_SECRET.encode()
    ).digest()


def generate_oauth_state() -> str:
    """Genera un state OAuth firmado con HMAC.

    Formato: ``{nonce}:{timestamp}:{signature}``
    """
    nonce = os.urandom(16).hex()
    timestamp = str(int(time.time()))
    payload = f"{nonce}:{timestamp}"
    signature = hmac.new(
        get_signing_key(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    return f"{payload}:{signature}"


def verify_oauth_state(
    state: str,
    max_age: int = _OAUTH_STATE_MAX_AGE_SECONDS,
) -> bool:
    """Verifica la firma y frescura de un state OAuth.

    Returns True si el formato es válido, la firma HMAC coincide y el
    timestamp no supera *max_age* segundos de antigüedad.
    """
    if not state:
        return False
    parts = state.split(":")
    if len(parts) != 3:
        return False
    nonce, timestamp_str, signature = parts
    try:
        ts = int(timestamp_str)
    except ValueError:
        return False
    if abs(time.time() - ts) > max_age:
        return False
    now = time.time()
    for seen_nonce, expires_at in list(_SEEN_OAUTH_NONCES.items()):
        if expires_at <= now:
            _SEEN_OAUTH_NONCES.pop(seen_nonce, None)
    if nonce in _SEEN_OAUTH_NONCES:
        return False
    payload = f"{nonce}:{timestamp_str}"
    expected = hmac.new(
        get_signing_key(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]
    valid = hmac.compare_digest(signature, expected)
    if valid:
        _SEEN_OAUTH_NONCES[nonce] = now + max_age
    return valid


# ---------------------------------------------------------------------------
# Email allowlist helpers
# ---------------------------------------------------------------------------


def csv_set(value: str) -> set[str]:
    """Convierte una cadena CSV a un conjunto de valores en minúsculas."""
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def oauth_email_allowed(email: str) -> bool:
    """Valida el email OAuth contra allowlists opcionales (settings)."""
    from config import settings

    normalized = email.strip().lower()
    allowed_emails = csv_set(settings.OAUTH_ALLOWED_EMAILS)
    allowed_domains = csv_set(settings.OAUTH_ALLOWED_DOMAINS)
    if not allowed_emails and not allowed_domains:
        return True
    domain = normalized.rsplit("@", 1)[-1] if "@" in normalized else ""
    return normalized in allowed_emails or domain in allowed_domains


def oauth_email_is_admin(email: str) -> bool:
    """True si el email está en la lista de admins OAuth."""
    from config import settings

    return email.strip().lower() in csv_set(settings.OAUTH_ADMIN_EMAILS)
