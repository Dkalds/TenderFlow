"""Tests de los endpoints de autenticación en /api/v1/auth.

No se duplican:
- Register + login happy path (en test_auth_register.py)

Los cinco tests de ``_sign_session``/``_verify_session`` se borraron el
2026-09-03 junto con las dos funciones: eran un JWT hecho a mano que no
llamaba ningún camino de producción, solo este fichero. El formato de sesión
real es opaco y revocable (``db/sessions.py``).
"""

from __future__ import annotations

# Fixtures client, auth, api_db se heredan de conftest.py

_VALID_PASSWORD = "P@ssw0rd1234"  # pragma: allowlist secret
_EMAIL = "sesion@example.com"


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
    r_logout = client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": r_login.cookies["csrf_token"]},
    )
    assert r_logout.status_code == 200

    # Verificar que /me ya no funciona (las cookies deben haberse eliminado
    # o expirado; el TestClient no seguirá enviando la cookie borrada)
    r_me = client.get("/api/v1/auth/me")
    assert r_me.status_code == 401
