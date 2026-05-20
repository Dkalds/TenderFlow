"""Rotación de claves de firma con `kid` (F4).

Soporta múltiples claves activas simultáneamente identificadas por su
``kid`` (key id), siguiendo el patrón JWKS de JWT. Esto permite rotar
``SIGNING_KEY`` sin invalidar tokens emitidos por la clave anterior
mientras dura su grace period.

Configuración vía variables de entorno:

* ``SIGNING_KEYS_JSON``: JSON ``{kid: key_b64}``. Ejemplo::

      {"k1": "secret-base64...", "k2": "next-secret-base64..."}

* ``SIGNING_KEY_ACTIVE``: ``kid`` que se usa para emitir nuevas firmas.
* ``SIGNING_KEY`` (legacy): si no hay ``SIGNING_KEYS_JSON``, se usa esta
  clave única con ``kid = "legacy"`` para compatibilidad.

API::

    from shared.signing import sign, verify

    token = sign(payload_bytes)           # {"kid": "...", "sig": "..."}
    ok = verify(payload_bytes, token)     # True/False
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from functools import lru_cache

from observability.logging import get_logger

log = get_logger(__name__)


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


@lru_cache(maxsize=1)
def _load_keys() -> tuple[dict[str, bytes], str]:
    """Carga el mapa kid→clave y devuelve ``(keys, active_kid)``.

    Cacheada para evitar reparseo en cada firma. Llamar a
    :func:`reload_keys` tras rotar para invalidar.
    """
    raw = os.getenv("SIGNING_KEYS_JSON", "").strip()
    keys: dict[str, bytes] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            keys = {str(k): _b64d(str(v)) for k, v in parsed.items()}
        except (ValueError, TypeError) as exc:
            log.warning("signing_keys_parse_error", error=str(exc))

    active = os.getenv("SIGNING_KEY_ACTIVE", "").strip()

    # Fallback legacy: SIGNING_KEY única
    if not keys:
        legacy = os.getenv("SIGNING_KEY", "").strip()
        if legacy:
            keys["legacy"] = legacy.encode("utf-8")
            active = active or "legacy"

    if not keys:
        # Modo demo/dev: clave efímera derivada de PID — NO PRODUCCIÓN.
        ephemeral = hashlib.sha256(f"dev-{os.getpid()}".encode()).digest()
        keys = {"dev": ephemeral}
        active = "dev"
        log.warning("signing_using_ephemeral_dev_key")

    if active not in keys:
        active = next(iter(keys))

    return keys, active


def reload_keys() -> None:
    """Invalida el caché tras rotación. Re-leerá de env en el siguiente uso."""
    _load_keys.cache_clear()


def sign(payload: bytes) -> str:
    """Firma ``payload`` con la clave activa y devuelve ``kid.sig`` en base64url."""
    keys, active = _load_keys()
    mac = hmac.new(keys[active], payload, hashlib.sha256).digest()
    return f"{active}.{_b64e(mac)}"


def verify(payload: bytes, token: str) -> bool:
    """Verifica ``token`` (formato ``kid.sig``) contra cualquier clave registrada.

    Permite rotación sin invalidar tokens emitidos por claves anteriores.
    """
    if not token or "." not in token:
        return False
    kid, sig_b64 = token.split(".", 1)
    keys, _ = _load_keys()
    key = keys.get(kid)
    if key is None:
        log.info("signing_unknown_kid", kid=kid)
        return False
    expected = hmac.new(key, payload, hashlib.sha256).digest()
    try:
        provided = _b64d(sig_b64)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, provided)


def active_kid() -> str:
    _, active = _load_keys()
    return active


def known_kids() -> tuple[str, ...]:
    keys, _ = _load_keys()
    return tuple(keys.keys())


__all__ = ["active_kid", "known_kids", "reload_keys", "sign", "verify"]
