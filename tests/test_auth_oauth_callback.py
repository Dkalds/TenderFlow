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


# ── La allowlist dice que no ────────────────────────────────────────────────
#
# El test de éxito de arriba y los de `test_s1_oauth_providers.py` sustituyen
# `_oauth_access_allowed` por un «sí» fijo, así que nada comprobaba qué hace el
# callback cuando la respuesta es «no». Lo que se fija aquí es que la negativa
# corta antes de crear nada: ni usuario, ni sesión, ni telemetría de login.


class _RespuestaDeToken:
    status_code = 200

    @staticmethod
    def json():
        return {"id_token": "signed-token"}


class _ClienteOAuth:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        return _RespuestaDeToken()


@pytest.fixture()
def callback_vigilado(monkeypatch):
    """Deja pasar todo lo anterior a la allowlist y apunta lo que ocurre después.

    Devuelve el módulo de rutas y la lista de lo que llegó a ejecutarse pasado
    el control de acceso. Con la dirección denegada tiene que quedar vacía.
    """
    from api.routes import auth as auth_routes

    ejecutado: list[str] = []

    def _apunta(nombre, valor=None):
        def _doble(*_args, **_kwargs):
            ejecutado.append(nombre)
            return valor

        return _doble

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(auth_routes, "verify_oauth_state", lambda _state: True)
    monkeypatch.setattr(auth_routes, "oauth_state_nonce", lambda _state: "nonce")
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", _ClienteOAuth)
    monkeypatch.setattr(auth_routes, "get_or_create_oauth_user", _apunta("usuario", 7))
    monkeypatch.setattr(auth_routes, "_sync_oauth_admin", _apunta("admin"))
    monkeypatch.setattr(auth_routes, "_activar_invitaciones", _apunta("invitaciones"))
    monkeypatch.setattr(auth_routes, "log_access", _apunta("acceso"))
    monkeypatch.setattr("db.totp.is_totp_required", _apunta("mfa", False))
    monkeypatch.setattr(auth_routes, "_set_session_cookie", _apunta("sesion", "csrf"))
    monkeypatch.setattr(auth_routes, "run_db", run_inline)
    return auth_routes, ejecutado


def _claims_de_google(monkeypatch, auth_routes, email):
    monkeypatch.setattr(
        auth_routes,
        "verify_google_id_token",
        lambda *_args, **_kwargs: {"email": email, "sub": "google-sub", "name": "Alguien"},
    )


def _llamar_al_callback(auth_routes):
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/oauth/google/callback",
            "headers": [],
            "client": ("testclient", 50000),
        }
    )
    return asyncio.run(
        auth_routes.google_callback(
            code="code",
            state="state",
            response=Response(),
            request=request,
            pkce_verifier="verifier",
        )
    )


def _afirma_denegado(result, ejecutado):
    assert result.status_code == 302
    assert result.headers["location"].endswith("/login?error=email_not_allowed")
    assert ejecutado == []
    cookies = result.headers.getlist("set-cookie")
    assert not any(cookie.startswith("session=") for cookie in cookies)
    assert not any("oauth_login" in cookie for cookie in cookies)


def test_callback_sin_acceso_redirige_sin_crear_usuario_ni_sesion(callback_vigilado, monkeypatch):
    auth_routes, ejecutado = callback_vigilado
    _claims_de_google(monkeypatch, auth_routes, "nadie@example.test")

    async def denegar(_email):
        return False

    monkeypatch.setattr(auth_routes, "_oauth_access_allowed", denegar)

    _afirma_denegado(_llamar_al_callback(auth_routes), ejecutado)


def test_callback_con_la_tabla_de_concesiones_caida_no_deja_entrar(callback_vigilado, monkeypatch):
    """Con la función real, no un doble: lista estática que no casa y Postgres caído."""
    auth_routes, ejecutado = callback_vigilado
    _claims_de_google(monkeypatch, auth_routes, "nadie@example.test")
    monkeypatch.setattr(auth_routes, "oauth_email_allowed", lambda _email: False)

    def _caida(_email):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("db.access_grants.is_access_granted", _caida)

    _afirma_denegado(_llamar_al_callback(auth_routes), ejecutado)


def test_callback_con_una_concesion_dinamica_deja_entrar(callback_vigilado, monkeypatch):
    """El otro lado del mismo camino: sin lista estática, la concesión basta."""
    auth_routes, ejecutado = callback_vigilado
    _claims_de_google(monkeypatch, auth_routes, "concedida@example.test")
    monkeypatch.setattr(auth_routes, "oauth_email_allowed", lambda _email: False)
    monkeypatch.setattr(
        "db.access_grants.is_access_granted", lambda email: email == "concedida@example.test"
    )

    result = _llamar_al_callback(auth_routes)

    assert result.headers["location"].endswith("/resumen")
    assert "usuario" in ejecutado
    assert "sesion" in ejecutado


@pytest.mark.parametrize(
    "email_del_token",
    [
        # Tras el último `@` hay un dominio que podría estar permitido.
        "x@evil.com@example.com",
        "@example.com",
        "persona@",
    ],
)
def test_callback_con_un_email_mal_formado_no_llega_a_la_allowlist(
    callback_vigilado, monkeypatch, email_del_token
):
    auth_routes, ejecutado = callback_vigilado
    _claims_de_google(monkeypatch, auth_routes, email_del_token)
    consultados: list[str] = []

    async def permitir(email):
        consultados.append(email)
        return True

    monkeypatch.setattr(auth_routes, "_oauth_access_allowed", permitir)

    _afirma_denegado(_llamar_al_callback(auth_routes), ejecutado)
    # Ni siquiera se pregunta: una allowlist abierta (`*`, o desarrollo sin
    # listas) no puede convertir esa cadena en la identidad de nadie.
    assert consultados == []
