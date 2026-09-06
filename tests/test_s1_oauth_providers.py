"""Tabla de proveedores OIDC: Microsoft entra, y Google entra igual que antes.

El riesgo de S1.2 es la regresión: el login de Google es el único que hoy usa
gente real. Por eso hay tanto test de Google como de Microsoft, y los de Google
comprueban justo lo que no debe haber cambiado — su endpoint de autorización,
su verificador y la ruta de su cookie PKCE.
"""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi import HTTPException, Request, Response

from api.routes import auth as auth_routes

_ROOT = Path(__file__).resolve().parents[1]

_DISCOVERY_SIMULADO = {
    "issuer": "https://login.microsoftonline.com/{tenantid}/v2.0",
    "authorization_endpoint": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    "token_endpoint": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
}


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/oauth/microsoft/callback",
            "headers": [],
            "client": ("testclient", 50000),
        }
    )


class _FakeTokenResponse:
    status_code = 200

    @staticmethod
    def json() -> dict[str, str]:
        return {"id_token": "token-firmado"}


class _FakeOAuthClient:
    """Cliente httpx simulado que registra a qué endpoint se canjeó el código."""

    ultimo_post: ClassVar[dict[str, Any]] = {}

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakeOAuthClient:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _FakeTokenResponse:
        type(self).ultimo_post = {"url": url, **kwargs}
        return _FakeTokenResponse()


@pytest.fixture()
def callback_sin_bd(monkeypatch):
    """Neutraliza todo lo que toca red o BD en el callback."""

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    async def allow_access(_email):
        return True

    monkeypatch.setattr(auth_routes, "verify_oauth_state", lambda _state: True)
    monkeypatch.setattr(auth_routes, "oauth_state_nonce", lambda _state: "nonce")
    monkeypatch.setattr(auth_routes, "_oauth_access_allowed", allow_access)
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", _FakeOAuthClient)
    monkeypatch.setattr(auth_routes, "get_or_create_oauth_user", lambda **_kwargs: 7)
    monkeypatch.setattr(auth_routes, "_sync_oauth_admin", lambda *_args: None)
    monkeypatch.setattr(auth_routes, "_activar_invitaciones", lambda *_args: None)
    monkeypatch.setattr(auth_routes, "log_access", lambda **_kwargs: None)
    monkeypatch.setattr("db.totp.is_totp_required", lambda _user_id: False)
    monkeypatch.setattr(auth_routes, "_set_session_cookie", lambda *_args: "csrf")
    monkeypatch.setattr(auth_routes, "run_db", run_inline)


@pytest.fixture()
def microsoft_configurado(monkeypatch):
    monkeypatch.setenv("OAUTH_MICROSOFT_CLIENT_ID", "microsoft-client-id")
    monkeypatch.setenv("OAUTH_MICROSOFT_CLIENT_SECRET", "microsoft-secret")
    monkeypatch.setenv("OAUTH_MICROSOFT_TENANT", "common")
    monkeypatch.setattr(
        auth_routes, "fetch_discovery_document", lambda _url: dict(_DISCOVERY_SIMULADO)
    )


# ── La tabla y el CHECK de la migración dicen lo mismo ──────────────────────


def test_los_proveedores_coinciden_con_el_check_de_la_migracion():
    """Un proveedor que la BD rechaza duplicaría la identidad de una persona."""
    migracion = (_ROOT / "db/alembic/versions/v105_users_oauth_provider.py").read_text(
        encoding="utf-8"
    )
    bloque = re.search(r"_PROVIDERS = \((.*?)\)", migracion, re.DOTALL)
    assert bloque is not None
    en_sql = tuple(re.findall(r'"([a-z]+)"', bloque.group(1)))

    assert en_sql == auth_routes.OAUTH_PROVIDERS


def test_un_proveedor_desconocido_es_404():
    with pytest.raises(HTTPException) as exc:
        auth_routes._provider_or_404("okta")

    assert exc.value.status_code == 404


# ── Correo del token ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("claims", "esperado"),
    [
        ({"email": "a@empresa.test"}, "a@empresa.test"),
        # Entra ID con cuenta de trabajo: sin `email`, el UPN es la identidad.
        ({"preferred_username": "b@empresa.test"}, "b@empresa.test"),
        ({"upn": "c@empresa.test"}, "c@empresa.test"),
        # Un `preferred_username` que no es un correo no vale como tal.
        ({"preferred_username": "solo-un-nombre"}, ""),
        ({}, ""),
    ],
)
def test_email_from_claims_cubre_las_formas_de_los_dos_proveedores(claims, esperado):
    assert auth_routes._email_from_claims(claims) == esperado


# ── Redirect URI derivado ───────────────────────────────────────────────────


def test_el_redirect_uri_de_microsoft_deriva_del_de_google(monkeypatch):
    monkeypatch.setattr(
        auth_routes.settings,
        "OAUTH_REDIRECT_URI",
        "https://api.example.test/api/v1/auth/oauth/google/callback",
        raising=False,
    )

    google = auth_routes._provider_redirect_uri(auth_routes._PROVIDERS["google"])
    microsoft = auth_routes._provider_redirect_uri(auth_routes._PROVIDERS["microsoft"])

    assert google == "https://api.example.test/api/v1/auth/oauth/google/callback"
    assert microsoft == "https://api.example.test/api/v1/auth/oauth/microsoft/callback"


# ── Authorize ───────────────────────────────────────────────────────────────


def test_authorize_de_microsoft_usa_el_endpoint_del_descubrimiento(
    monkeypatch, microsoft_configurado
):
    response = Response()

    resultado = asyncio.run(auth_routes.oauth_authorize("microsoft", response))

    url = urllib.parse.urlparse(resultado.authorization_url)
    params = urllib.parse.parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}{url.path}" == _DISCOVERY_SIMULADO["authorization_endpoint"]
    assert params["client_id"] == ["microsoft-client-id"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid email profile"]
    assert params["nonce"] and params["state"]
    # El verifier PKCE solo viaja al callback de SU proveedor.
    assert "Path=/api/v1/auth/oauth/microsoft" in response.headers["set-cookie"]


def test_authorize_de_microsoft_sin_configurar_responde_501(monkeypatch):
    monkeypatch.delenv("OAUTH_MICROSOFT_CLIENT_ID", raising=False)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(auth_routes.oauth_authorize("microsoft", Response()))

    assert exc.value.status_code == 501


def test_regresion_authorize_de_google_no_cambia(monkeypatch):
    """Mismo endpoint, mismos parámetros propios y misma cookie que antes."""
    monkeypatch.setattr(auth_routes.settings, "GOOGLE_CLIENT_ID", "google-id", raising=False)

    def _no_descubrimiento(_url):  # pragma: no cover - debe no llamarse
        raise AssertionError("Google no debe salir a un documento de descubrimiento")

    monkeypatch.setattr(auth_routes, "fetch_discovery_document", _no_descubrimiento)
    response = Response()

    resultado = asyncio.run(auth_routes.google_authorize(response))

    assert resultado.authorization_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(resultado.authorization_url).query)
    assert params["access_type"] == ["online"]
    assert params["prompt"] == ["select_account"]
    assert params["client_id"] == ["google-id"]
    assert "Path=/api/v1/auth/oauth/google" in response.headers["set-cookie"]


# ── Callback ────────────────────────────────────────────────────────────────


def test_callback_de_microsoft_sobre_un_descubrimiento_simulado(
    monkeypatch, microsoft_configurado, callback_sin_bd
):
    verificados: list[dict[str, Any]] = []

    def _verify(raw, *, jwks_uri, issuer, audience, expected_nonce):
        verificados.append(
            {
                "raw": raw,
                "jwks_uri": jwks_uri,
                "issuer": issuer,
                "audience": audience,
                "nonce": expected_nonce,
            }
        )
        return {"preferred_username": "persona@empresa.test", "sub": "ms-sub", "name": "Persona"}

    proveedores: list[str] = []
    monkeypatch.setattr(auth_routes, "verify_oidc_id_token", _verify)
    monkeypatch.setattr(
        auth_routes,
        "get_or_create_oauth_user",
        lambda **kwargs: (proveedores.append(kwargs["oauth_provider"]), 7)[1],
    )

    resultado = asyncio.run(
        auth_routes.oauth_callback(
            provider="microsoft",
            code="code",
            state="state",
            response=Response(),
            request=_request(),
            pkce_verifier="verifier",
        )
    )

    assert resultado.status_code == 302
    assert resultado.headers["location"].endswith("/resumen")
    # El código se canjeó contra el token_endpoint del descubrimiento, no
    # contra una URL escrita a mano.
    assert _FakeOAuthClient.ultimo_post["url"] == _DISCOVERY_SIMULADO["token_endpoint"]
    assert verificados[0]["jwks_uri"] == _DISCOVERY_SIMULADO["jwks_uri"]
    assert verificados[0]["issuer"] == _DISCOVERY_SIMULADO["issuer"]
    assert verificados[0]["audience"] == "microsoft-client-id"
    # `users.oauth_provider` guarda el proveedor con el que se entró (v105).
    assert proveedores == ["microsoft"]


def test_callback_de_microsoft_marca_el_proveedor_en_la_telemetria(
    monkeypatch, microsoft_configurado, callback_sin_bd
):
    monkeypatch.setattr(
        auth_routes,
        "verify_oidc_id_token",
        lambda *_a, **_k: {"email": "persona@empresa.test", "sub": "ms-sub"},
    )

    resultado = asyncio.run(
        auth_routes.oauth_callback(
            provider="microsoft",
            code="code",
            state="state",
            response=Response(),
            request=_request(),
            pkce_verifier="verifier",
        )
    )

    cookies = resultado.headers.getlist("set-cookie")
    # La cookie histórica sigue con el mismo valor: el componente que la lee
    # compara contra `oauth_login=1` exacto y no es de este stream.
    assert any(c.startswith("oauth_login=1;") for c in cookies)
    assert any(c.startswith("oauth_login_provider=microsoft;") for c in cookies)
    # Nada que identifique a la persona viaja en la telemetría.
    assert not any("persona@empresa.test" in c for c in cookies)


def test_regresion_callback_de_google_sigue_usando_su_verificador(monkeypatch, callback_sin_bd):
    """El camino que hoy usa gente real: mismo verificador y mismo proveedor."""
    monkeypatch.setattr(auth_routes.settings, "GOOGLE_CLIENT_ID", "google-id", raising=False)
    llamadas: list[str] = []
    proveedores: list[str] = []

    def _verify_google(raw, *, audience, expected_nonce):
        llamadas.append(raw)
        assert audience == "google-id"
        return {"email": "persona@empresa.test", "sub": "google-sub", "name": "Persona"}

    def _verify_generico(*_args, **_kwargs):  # pragma: no cover - no debe llamarse
        raise AssertionError("Google no debe pasar por el verificador genérico")

    monkeypatch.setattr(auth_routes, "verify_google_id_token", _verify_google)
    monkeypatch.setattr(auth_routes, "verify_oidc_id_token", _verify_generico)
    monkeypatch.setattr(
        auth_routes,
        "get_or_create_oauth_user",
        lambda **kwargs: (proveedores.append(kwargs["oauth_provider"]), 7)[1],
    )

    resultado = asyncio.run(
        auth_routes.google_callback(
            code="code",
            state="state",
            response=Response(),
            request=_request(),
            pkce_verifier="verifier",
        )
    )

    assert resultado.status_code == 302
    assert resultado.headers["location"].endswith("/resumen")
    assert llamadas == ["token-firmado"]
    assert proveedores == ["google"]
    assert _FakeOAuthClient.ultimo_post["url"] == "https://oauth2.googleapis.com/token"
