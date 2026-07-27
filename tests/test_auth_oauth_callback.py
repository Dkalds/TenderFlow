"""Tests del endpoint ``GET /api/v1/auth/oauth/google/callback``.

El callback lo entrega Google mediante una navegación de nivel superior del
navegador (no un fetch del SPA), así que cualquier fallo debe redirigir a
/login?error=<slug> en vez de servir un HTTPException como JSON crudo — de
lo contrario el usuario ve un blob JSON en blanco en pantalla.
"""

from __future__ import annotations


def test_callback_invalid_state_redirects_to_login(client):
    resp = client.get(
        "/api/v1/auth/oauth/google/callback",
        params={"code": "fake-code", "state": "not-a-valid-state"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert location.endswith("/login?error=invalid_state")
    # No debe filtrar un HTTPException como JSON crudo.
    assert "detail" not in resp.text


def test_callback_expired_or_replayed_state_redirects_to_login(client, monkeypatch):
    from shared.auth_core import generate_oauth_state

    monkeypatch.setattr("shared.auth_core._OAUTH_STATE_MAX_AGE_SECONDS", 600)
    state = generate_oauth_state()

    # Un state ya usado (replay) o caducado falla la misma verificación que
    # uno con formato inválido — mismo slug de error para el usuario.
    from shared import auth_core

    auth_core._reset_nonce_store()
    store = auth_core._get_nonce_store()
    store.add(state.split(":")[0], 600)

    resp = client.get(
        "/api/v1/auth/oauth/google/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/login?error=invalid_state")
    auth_core._reset_nonce_store()


def test_callback_missing_pkce_verifier_redirects_to_login(client):
    from shared.auth_core import generate_oauth_state

    state = generate_oauth_state()

    # Sin la cookie oauth_pkce (ej. el usuario abrió el link en otro navegador).
    resp = client.get(
        "/api/v1/auth/oauth/google/callback",
        params={"code": "fake-code", "state": state},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/login?error=invalid_state")


def test_callback_error_redirect_clears_pkce_cookie(client):
    client.cookies.set("oauth_pkce", "some-verifier")
    resp = client.get(
        "/api/v1/auth/oauth/google/callback",
        params={"code": "fake-code", "state": "not-a-valid-state"},
        follow_redirects=False,
    )
    set_cookie_headers = resp.headers.get_list("set-cookie")
    assert any("oauth_pkce=" in h and "Max-Age=0" in h for h in set_cookie_headers)
