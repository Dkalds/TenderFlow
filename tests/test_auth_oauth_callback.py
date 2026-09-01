"""Tests del endpoint ``GET /api/v1/auth/oauth/google/callback``.

El callback lo entrega Google mediante una navegación de nivel superior del
navegador (no un fetch del SPA), así que cualquier fallo debe redirigir a
/login?error=<slug> en vez de servir un HTTPException como JSON crudo — de
lo contrario el usuario ve un blob JSON en blanco en pantalla.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import Request, Response


@pytest.mark.parametrize(
    ("mfa_required", "telemetry_cookie_expected"),
    [(False, True), (True, False)],
)
def test_callback_success_sets_telemetry_cookie_only_without_mfa(
    monkeypatch, mfa_required, telemetry_cookie_expected
):
    from api.routes import auth as auth_routes

    class FakeTokenResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"id_token": "signed-token"}

    class FakeOAuthClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeTokenResponse()

    async def allow_access(_email):
        return True

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(auth_routes, "verify_oauth_state", lambda _state: True)
    monkeypatch.setattr(auth_routes, "oauth_state_nonce", lambda _state: "nonce")
    monkeypatch.setattr(
        auth_routes,
        "verify_google_id_token",
        lambda *_args, **_kwargs: {
            "email": "allowed@example.test",
            "sub": "google-sub",
            "name": "Allowed User",
        },
    )
    monkeypatch.setattr(auth_routes, "_oauth_access_allowed", allow_access)
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", FakeOAuthClient)
    monkeypatch.setattr(auth_routes, "get_or_create_oauth_user", lambda **_kwargs: 7)
    monkeypatch.setattr(auth_routes, "_sync_oauth_admin", lambda *_args: None)
    monkeypatch.setattr(auth_routes, "log_access", lambda **_kwargs: None)
    monkeypatch.setattr("db.totp.is_totp_required", lambda _user_id: mfa_required)
    monkeypatch.setattr(auth_routes, "_set_session_cookie", lambda *_args: "csrf")
    monkeypatch.setattr(auth_routes, "run_db", run_inline)

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/oauth/google/callback",
            "headers": [],
            "client": ("testclient", 50000),
        }
    )
    result = asyncio.run(
        auth_routes.google_callback(
            code="code",
            state="state",
            response=Response(),
            request=request,
            pkce_verifier="verifier",
        )
    )

    cookies = result.headers.getlist("set-cookie")
    has_telemetry_cookie = any("oauth_login=1" in cookie for cookie in cookies)
    assert has_telemetry_cookie is telemetry_cookie_expected
    expected_destination = "/login?mfa=required" if mfa_required else "/resumen"
    assert result.headers["location"].endswith(expected_destination)


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
