"""Derivación de secretos para webhooks (issue #49).

En lugar de almacenar secretos en texto plano en la BD, derivamos la clave
de firma de cada webhook a partir de una clave maestra del servidor:

    signing_key = HMAC-SHA256(master_key, "webhook-v1:{webhook_id}")

El secreto derivado se devuelve al usuario una sola vez en la creación.
En cada entrega, se re-deriva desde la master key + webhook_id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

_DERIVATION_PREFIX = "webhook-v1"

# Sentinel value stored in DB instead of the real secret.
DERIVED_SECRET_SENTINEL = "derived:v1"  # noqa: S105


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


__all__ = [
    "DERIVED_SECRET_SENTINEL",
    "derive_webhook_secret",
    "is_derived_secret",
]
