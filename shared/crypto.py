"""Criptografía compartida: secretos y firma de webhooks + cifrado TOTP.

Webhook secrets (issue #49):
    En lugar de almacenar secretos en texto plano en la BD, derivamos la clave
    de firma de cada webhook a partir de una clave maestra del servidor:

        signing_key = HMAC-SHA256(master_key, "webhook-v1:{webhook_id}")

    El secreto derivado se devuelve al usuario una sola vez en la creación.
    En cada entrega, se re-deriva desde la master key + webhook_id.

Rotación (Ola 1 · Webhooks):
    La derivación v1 es determinista —clave maestra + id— y por eso no se puede
    rotar sin borrar el webhook: volver a derivar da el mismo secreto. La
    rotación añade **material por webhook**, que se guarda en la misma columna
    ``secret`` dentro del sentinel (``derived:v2:<material>``) y entra en el
    contexto de derivación:

        signing_key = HMAC-SHA256(master_key, "webhook-v2:{webhook_id}:{material}")

    El material solo no sirve para firmar —hace falta la clave maestra, que
    sigue fuera de la BD—, así que la garantía de RFC 049 se conserva. Rotar
    es escribir material nuevo: el secreto anterior deja de derivarse en el
    mismo instante, sin periodo de gracia.

Firma de entregas:
    Dos cabeceras sobre el mismo secreto. ``X-Webhook-Signature`` (v1) firma el
    cuerpo tal cual y se mantiene por compatibilidad. ``X-Webhook-Signature-V2``
    liga además el sello ``X-Webhook-Timestamp`` (segundos Unix) al cuerpo —
    ``HMAC-SHA256(secret, "{timestamp}.{body}")``— para que el receptor pueda
    rechazar una entrega capturada y reenviada fuera de la ventana
    :data:`VENTANA_REPLAY_S`. Un reintento reutiliza el sello original: la
    firma v2 de un mismo evento es la misma en todos los intentos.

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
from datetime import UTC, datetime
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from observability.logging import get_logger

log = get_logger(__name__)

# ── Webhook secret derivation ────────────────────────────────────────────

_DERIVATION_PREFIX = "webhook-v1"
_DERIVATION_PREFIX_V2 = "webhook-v2"

# Sentinel value stored in DB instead of the real secret.
DERIVED_SECRET_SENTINEL = "derived:v1"  # noqa: S105  # pragma: allowlist secret

#: Prefijo del sentinel con material por webhook: ``derived:v2:<material>``.
#: Sigue empezando por ``derived:`` para que :func:`is_derived_secret` lo
#: reconozca sin cambios en los tres sitios que lo consultan.
DERIVED_SECRET_SENTINEL_V2_PREFIX = "derived:v2:"  # noqa: S105  # pragma: allowlist secret


def derive_webhook_secret(master_key: str, webhook_id: int, material: str | None = None) -> str:
    """Derive a per-webhook signing key from the server master key.

    Sin ``material`` es la derivación v1 (clave maestra + id), la de todos los
    webhooks creados antes de la rotación. Con ``material`` —el que guarda el
    sentinel ``derived:v2:<material>``— el contexto cambia y con él el secreto,
    que es exactamente lo que una rotación necesita.

    Returns a URL-safe base64 string suitable for HMAC signing.
    """
    if not master_key:
        raise ValueError("master_key must not be empty")
    if material is None:
        context = f"{_DERIVATION_PREFIX}:{webhook_id}".encode()
    else:
        context = f"{_DERIVATION_PREFIX_V2}:{webhook_id}:{material}".encode()
    derived = hmac.new(
        master_key.encode("utf-8"),
        context,
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(derived).rstrip(b"=").decode("ascii")


def is_derived_secret(secret: str) -> bool:
    """Check whether a stored secret is the derivation sentinel."""
    return secret.startswith("derived:")


def nuevo_material_de_secreto() -> str:
    """Material aleatorio para una rotación (128 bits, base64 URL-safe).

    Se guarda en claro dentro del sentinel: sin la clave maestra no deriva
    nada, así que no es un secreto por sí mismo.
    """
    return base64.urlsafe_b64encode(os.urandom(16)).rstrip(b"=").decode("ascii")


def sentinel_rotado(material: str) -> str:
    """Valor de la columna ``secret`` para un webhook con material propio."""
    if not material:
        raise ValueError("material must not be empty")
    return f"{DERIVED_SECRET_SENTINEL_V2_PREFIX}{material}"


def material_de_secreto(stored: str) -> str | None:
    """Material embebido en un sentinel ``derived:v2:<material>``; ``None`` en v1."""
    if stored.startswith(DERIVED_SECRET_SENTINEL_V2_PREFIX):
        material = stored[len(DERIVED_SECRET_SENTINEL_V2_PREFIX) :]
        if material:
            return material
    return None


def resolve_derived_secret(master_key: str, webhook_id: int, stored: str) -> str:
    """Secreto efectivo a partir del sentinel almacenado (v1 o v2).

    Es el único sitio que sabe leer el sentinel: los tres resolutores de
    ``db/`` (``_resolve_secret``, ``resolve_stored_secret`` y
    ``WebhookRepository.get_secret``) delegan aquí para que una rotación no
    pueda quedar reconocida en un despachador y no en otro.
    """
    return derive_webhook_secret(master_key, webhook_id, material_de_secreto(stored))


# ── Webhook delivery signing ─────────────────────────────────────────────

#: Tolerancia recomendada al receptor entre ``X-Webhook-Timestamp`` y su reloj.
#: Cinco minutos absorbe el desfase de reloj habitual y sigue dejando fuera
#: una entrega capturada y reenviada horas después.
VENTANA_REPLAY_S = 300


def firmar_webhook(secret: str, body: bytes) -> str:
    """Firma v1: ``HMAC-SHA256(secret, body)`` en hex. Va en ``X-Webhook-Signature``."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def firmar_webhook_v2(secret: str, timestamp: int, body: bytes) -> str:
    """Firma v2: ``HMAC-SHA256(secret, "{timestamp}." + body)`` en hex.

    El sello va **delante** del cuerpo y separado por un punto, sobre los bytes
    crudos: el receptor no tiene que re-serializar el JSON para verificar, y
    un cuerpo idéntico con otro sello da otra firma.
    """
    return hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode("ascii") + body, hashlib.sha256
    ).hexdigest()


def cabeceras_de_firma(*, secret: str, body: bytes, timestamp: int) -> dict[str, str]:
    """Las tres cabeceras de autenticidad de una entrega.

    ``X-Webhook-Signature`` se conserva sin cambios (hay receptores en
    producción que solo verifican esa); las otras dos son las que permiten
    rechazar un replay. El sello es el de la entrega original: un reintento
    lo reutiliza en vez de regenerarlo.
    """
    return {
        "X-Webhook-Signature": f"sha256={firmar_webhook(secret, body)}",
        "X-Webhook-Timestamp": str(int(timestamp)),
        "X-Webhook-Signature-V2": f"v2={firmar_webhook_v2(secret, timestamp, body)}",
    }


def segundos_unix(marca: str | datetime) -> int:
    """Segundos Unix (enteros, truncados) de una marca ISO 8601 o un ``datetime``.

    Acepta el sufijo ``Z`` y el offset corto de Postgres (``+00``); una marca
    sin zona se interpreta como UTC, que es como las escribe ``now_utc_iso``.
    Lanza ``ValueError`` si la marca no es una fecha: el llamante decide el
    fallback, porque un sello inventado firmaría algo que no ocurrió.
    """
    if isinstance(marca, datetime):
        momento = marca
    else:
        momento = datetime.fromisoformat(marca.strip().replace("Z", "+00:00"))
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)
    return int(momento.timestamp())


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
    "DERIVED_SECRET_SENTINEL_V2_PREFIX",
    "VENTANA_REPLAY_S",
    "TOTPDecryptionError",
    "cabeceras_de_firma",
    "decrypt_totp_secret",
    "derive_webhook_secret",
    "encrypt_totp_secret",
    "firmar_webhook",
    "firmar_webhook_v2",
    "is_derived_secret",
    "is_encrypted",
    "material_de_secreto",
    "nuevo_material_de_secreto",
    "reload_encryption_key",
    "resolve_derived_secret",
    "segundos_unix",
    "sentinel_rotado",
]
