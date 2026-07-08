"""Tests de session helpers y endpoints de autenticación en /api/v1/auth.

No se duplican:
- Register + login happy path (en test_auth_register.py)
"""

from __future__ import annotations

import time

from api.routes.auth import _sign_session, _verify_session

# Fixtures client, auth, api_db se heredan de conftest.py

_VALID_PASSWORD = "P@ssw0rd1234"  # pragma: allowlist secret
_EMAIL = "sesion@example.com"


# ---------------------------------------------------------------------------
# Helpers de sesión: _sign_session / _verify_session
# ---------------------------------------------------------------------------


def test_verify_session_token_invalido():
    """Token sin punto (sin separador) → None."""
    result = _verify_session("tokensinpunto")
    assert result is None


def test_verify_session_base64_malo():
    """Base64 inválido antes del punto → None."""
    result = _verify_session("!!!invalido!!!.deadbeef")
    assert result is None


def test_verify_session_firma_mala():
    """Firma incorrecta (hex modificado) → None."""
    valid = _sign_session({"user_id": 1, "exp": int(time.time()) + 3600})
    b64, _ = valid.split(".", 1)
    tampered = f"{b64}.0000000000000000000000000000000000000000000000000000000000000000"
    assert _verify_session(tampered) is None


def test_verify_session_expirado():
    """Token con exp en el pasado → None."""
    token = _sign_session({"user_id": 1, "exp": int(time.time()) - 1})
    assert _verify_session(token) is None


def test_verify_session_roundtrip():
    """sign → verify devuelve el mismo payload (user_id intacto)."""
    exp = int(time.time()) + 3600
    payload = {"user_id": 42, "exp": exp}
    token = _sign_session(payload)
    result = _verify_session(token)
    assert result is not None
    assert result["user_id"] == 42
    assert result["exp"] == exp


# ---------------------------------------------------------------------------
# GET /me  — requiere cookie de sesión, no API key
# ---------------------------------------------------------------------------


def test_me_sin_cookie(client, auth):
    """/me con API key pero sin cookie de sesión → 401.

    get_current_session_user lee la cookie 'session'; sin ella devuelve 401
    independientemente de que el cliente lleve cabecera X-API-Key válida.
    """
    # Usamos el client del conftest (autenticado por API key); /me requiere
    # cookie de sesión, no API key, así que debe responder 401.
    r = client.get("/api/v1/auth/me", headers=auth)
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# POST /logout — limpia las cookies de sesión
# ---------------------------------------------------------------------------


def test_logout_limpia_cookies(client):
    """Register → login → logout: las cookies session/csrf_token se borran."""
    # Registrar usuario
    r_reg = client.post(
        "/api/v1/auth/register",
        json={"email": _EMAIL, "password": _VALID_PASSWORD},
    )
    assert r_reg.status_code == 201, r_reg.text

    # Login explícito (aunque register ya hace auto-login, lo repetimos para
    # asegurarnos de que el TestClient tiene la cookie fresca)
    r_login = client.post(
        "/api/v1/auth/login",
        json={"email": _EMAIL, "password": _VALID_PASSWORD},
    )
    assert r_login.status_code == 200, r_login.text
    assert "session" in r_login.cookies

    # Logout
    r_logout = client.post("/api/v1/auth/logout")
    assert r_logout.status_code == 200

    # Verificar que /me ya no funciona (las cookies deben haberse eliminado
    # o expirado; el TestClient no seguirá enviando la cookie borrada)
    r_me = client.get("/api/v1/auth/me")
    assert r_me.status_code == 401
