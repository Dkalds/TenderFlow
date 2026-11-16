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

Periodo de gracia (cerrado el 2026-11-16)
-----------------------------------------

Al cambiar de formato, :func:`csrf_token_valido` aceptó también el token
anterior —HMAC-SHA256 plano de la clave de firma, sin ``kid`` ni caducidad—
mientras lo dijera ``CSRF_ACEPTAR_LEGACY`` (por defecto, sí), para no dar un 403
a quien tenía sesión abierta. Tenía que durar un ciclo de sesión desde
septiembre, pero nadie fijó la variable a ``0`` y la gracia seguía abierta dos
meses después. Se retiró el código y la variable: hoy solo vale el formato
vigente, y una sesión anterior a septiembre ya caducó por su techo absoluto.

Uso::

    from shared.csrf import csrf_token_valido, generate_csrf_token

    token = generate_csrf_token(session_id)
    ok = csrf_token_valido(recibido, session_id, max_age=86400)
"""

from __future__ import annotations

import hashlib
import time

from shared.signing import sign, verify

# Default max age: 1 hour
DEFAULT_MAX_AGE_SECONDS: int = 3600


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


def csrf_token_valido(
    token: str | None,
    session_id: str,
    *,
    max_age: int = DEFAULT_MAX_AGE_SECONDS,
) -> bool:
    """Punto de validación único del sistema: solo el formato vigente.

    Un token vacío o ausente nunca es válido: la ausencia de credencial no es
    un caso a tolerar, es el ataque.
    """
    if not token or not session_id:
        return False
    return validate_csrf_token(token, session_id, max_age=max_age)


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "csrf_token_valido",
    "generate_csrf_token",
    "validate_csrf_token",
]
