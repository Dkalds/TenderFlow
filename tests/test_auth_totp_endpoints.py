"""Pruebas del flujo MFA real: alta, desafÃ­o y elevaciÃ³n de sesiÃ³n."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from urllib.parse import parse_qs, urlparse


def _current_totp(secret: str) -> str:
    """Calcula el TOTP RFC 6238 que aceptarÃ­a un autenticador externo."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    counter = int(time.time() // 30)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFF_FFFF
    return f"{value % 1_000_000:06d}"


def test_totp_confirmation_requires_a_second_factor_before_access(client):
    password = "Teal47!Orbit"  # pragma: allowlist secret -- contraseña ficticia de test
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": "mfa@example.com", "password": password},
    )
    assert registered.status_code == 201, registered.text
    csrf = registered.cookies["csrf_token"]

    setup = client.post("/api/v1/auth/totp/setup", headers={"X-CSRF-Token": csrf})
    assert setup.status_code == 200
    secret = parse_qs(urlparse(setup.json()["otpauth_uri"]).query)["secret"][0]
    code = _current_totp(secret)

    confirmed = client.post(
        "/api/v1/auth/totp/confirm",
        json={"code": code},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    assert len(confirmed.json()["recovery_codes"]) == 10

    logged_out = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert logged_out.status_code == 200
    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "mfa@example.com", "password": password},
    )
    assert logged_in.status_code == 200
    next_csrf = logged_in.cookies["csrf_token"]

    blocked = client.get("/api/v1/me/keys")
    assert blocked.status_code == 403

    verified = client.post(
        "/api/v1/auth/totp/verify",
        json={"code": code},
        headers={"X-CSRF-Token": next_csrf},
    )
    assert verified.status_code == 200
    assert client.get("/api/v1/me/keys").status_code == 200
