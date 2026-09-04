"""Tokens CSRF firmados con HMAC, ligados a la sesión, con ``kid`` y caducidad.

Formato vigente: ``{session_hash}:{timestamp}:{kid}.{sig}``

* ``session_hash`` — 16 primeros hex de SHA-256(session_id); no filtra el token
  de sesión en bruto ni siquiera a quien lea la cookie CSRF (que es legible por
  JavaScript, porque el patrón double-submit lo exige).
* ``timestamp`` — epoch de emisión. Da caducidad propia al token.
* ``kid.sig`` — firma de :mod:`shared.signing`, que lleva ``kid`` y por tanto
  admite rotar ``SIGNING_KEY`` sin invalidar lo ya emitido.

Historia (2026-09-03): había **tres** implementaciones de CSRF conviviendo.
``api/routes/auth.py::_csrf_for_session`` derivaba un HMAC plano de la clave y
el token de sesión —sin ``kid`` y sin caducidad—, ``api/routes/dual_auth.py``
reimplementaba inline esa misma comparación, y este módulo, que es el que tiene
las tres propiedades que se quieren, **no lo importaba nadie fuera de su test**.
Ahora este módulo es el formato único; los otros dos llaman aquí.

Periodo de gracia
-----------------

Emitir el formato nuevo invalidaría de golpe la cookie ``csrf_token`` de todo
el que tenga sesión abierta: su siguiente mutación saldría 403 y, para el
usuario, eso es un logout con un error raro. Por eso :func:`csrf_token_valido`
acepta **los dos formatos** durante el periodo de gracia, controlado por la
variable de entorno ``CSRF_ACEPTAR_LEGACY``:

* ``1`` (default) — se acepta el token legacy además del nuevo. Es el estado
  en el que hay que desplegar.
* ``0`` — solo el formato nuevo. Es el fin del periodo de gracia; se pone
  cuando ya no queden sesiones anteriores al despliegue, es decir tras
  ``_SESSION_MAX_AGE`` (24 h) desde que salió a producción.

El formato legacy **no** se emite nunca más: el periodo de gracia solo acepta,
no produce. Y como el token legacy no lleva ``kid``, se valida contra la clave
de firma activa: al rotar ``SIGNING_KEY`` los tokens legacy dejan de verificar
—el nuevo formato sí sobrevive a la rotación, que es medio motivo del cambio—.

Uso::

    from shared.csrf import csrf_token_valido, generate_csrf_token

    token = generate_csrf_token(session_id)
    ok = csrf_token_valido(recibido, session_id, max_age=86400)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from shared.signing import sign, verify

# Default max age: 1 hour
DEFAULT_MAX_AGE_SECONDS: int = 3600

#: Nombre de la variable de entorno que gobierna el periodo de gracia.
LEGACY_GRACE_ENV = "CSRF_ACEPTAR_LEGACY"


def _session_hash(session_id: str) -> str:
    """Return a truncated SHA-256 hex digest of *session_id*."""
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]


def generate_csrf_token(session_id: str) -> str:
    """Generate an HMAC-signed CSRF token bound to *session_id*.

    Args:
        session_id: The raw session token (cookie value).

    Returns:
        A string ``{session_hash}:{timestamp}:{signature}`` safe for
        embedding in hidden form fields or custom HTTP headers.
    """
    if not session_id:
        raise ValueError("session_id must not be empty")
    s_hash = _session_hash(session_id)
    ts = str(int(time.time()))
    payload = f"{s_hash}:{ts}".encode()
    sig = sign(payload)
    return f"{s_hash}:{ts}:{sig}"


def validate_csrf_token(
    token: str,
    session_id: str,
    *,
    max_age: int = DEFAULT_MAX_AGE_SECONDS,
) -> bool:
    """Validate a CSRF token against *session_id* and freshness.

    Checks:
    1. Token format is correct (3+ colon-separated parts).
    2. Session hash matches the provided *session_id*.
    3. Timestamp is within *max_age* seconds of now.
    4. HMAC signature is valid (via :func:`shared.signing.verify`).

    Args:
        token: The CSRF token string to validate.
        session_id: The raw session token from the cookie.
        max_age: Maximum age in seconds (default 3600).

    Returns:
        ``True`` if the token is valid; ``False`` otherwise.
    """
    if not token or not session_id:
        return False

    # Format: session_hash:timestamp:kid.sig
    # The signature part contains a dot, so we split on ":" with maxsplit=2
    parts = token.split(":", 2)
    if len(parts) != 3:
        return False

    s_hash, ts_str, sig = parts

    # 1. Session binding
    expected_hash = _session_hash(session_id)
    if s_hash != expected_hash:
        return False

    # 2. Freshness
    try:
        ts = int(ts_str)
    except ValueError:
        return False
    if abs(time.time() - ts) > max_age:
        return False

    # 3. Signature verification
    payload = f"{s_hash}:{ts_str}".encode()
    return verify(payload, sig)


# ── Formato legacy: se acepta durante la gracia, no se emite nunca ──────────


def legacy_csrf_token(session_id: str) -> str:
    """Token en el formato anterior: HMAC-SHA256 plano de la clave de firma.

    Se conserva **solo** para poder reconocer las cookies ya emitidas mientras
    dure el periodo de gracia. No lleva ``kid`` (no sobrevive a una rotación)
    ni caducidad propia (vive lo que viva la sesión), que son justo las dos
    razones por las que se sustituye.
    """
    from shared.auth_core import get_signing_key

    return hmac.new(get_signing_key(), session_id.encode(), hashlib.sha256).hexdigest()


def legacy_aceptado() -> bool:
    """¿Sigue abierto el periodo de gracia? Ver el docstring del módulo."""
    return os.getenv(LEGACY_GRACE_ENV, "1").strip().lower() not in ("0", "false", "no")


def csrf_token_valido(
    token: str | None,
    session_id: str,
    *,
    max_age: int = DEFAULT_MAX_AGE_SECONDS,
) -> bool:
    """Punto de validación único del sistema. Acepta el formato nuevo siempre.

    Acepta además el legacy mientras dure el periodo de gracia
    (``CSRF_ACEPTAR_LEGACY``). Un token vacío o ausente nunca es válido: la
    ausencia de credencial no es un caso a tolerar, es el ataque.
    """
    if not token or not session_id:
        return False
    if validate_csrf_token(token, session_id, max_age=max_age):
        return True
    if not legacy_aceptado():
        return False
    return hmac.compare_digest(token, legacy_csrf_token(session_id))


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "LEGACY_GRACE_ENV",
    "csrf_token_valido",
    "generate_csrf_token",
    "legacy_aceptado",
    "legacy_csrf_token",
    "validate_csrf_token",
]
