"""Entra con un correo que no consta como suyo no se queda con la cuenta de nadie.

ADR-037. Dos piezas, y los tests de abajo cubren cada una por separado y las
dos juntas por el callback real:

- ``shared.identity.verify_oidc_id_token`` exige ``xms_edov`` a Microsoft: sin
  él, el correo del token es lo que el administrador del tenant quiso escribir.
- ``db.users.get_or_create_oauth_user`` no vincula una identidad a una cuenta
  que ya entra con **otro** proveedor solo porque el correo coincide.

El token se firma de verdad con una clave RSA efímera y su JWK se sirve desde
un JWKS simulado: es la única forma de comprobar que lo que rechaza el callback
es un token **válido** sin correo acreditado, y no uno mal firmado.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, ClassVar

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import Request, Response

from api.routes import auth as auth_routes
from shared import identity

_TENANT = "11111111-2222-3333-4444-555555555555"
_CLIENT_ID = "microsoft-client-id"
_DISCOVERY = {
    "issuer": "https://login.microsoftonline.com/{tenantid}/v2.0",
    "authorization_endpoint": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
    "token_endpoint": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
    "jwks_uri": "https://login.microsoftonline.com/common/discovery/v2.0/keys",
}
_NONCE = "nonce-de-prueba"
_VICTIMA = "victima@empresa.test"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_json(data: dict[str, Any]) -> str:
    return _b64u(json.dumps(data, separators=(",", ":")).encode("utf-8"))


def _b64u_uint(value: int) -> str:
    return _b64u(value.to_bytes((value.bit_length() + 7) // 8, "big"))


@pytest.fixture()
def clave_rsa() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _firmar(clave: rsa.RSAPrivateKey, claims: dict[str, Any]) -> str:
    header = _b64u_json({"alg": "RS256", "kid": "kid-de-prueba", "typ": "JWT"})
    cuerpo = _b64u_json(claims)
    firma = clave.sign(f"{header}.{cuerpo}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{cuerpo}.{_b64u(firma)}"


def _claims_entra(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "iss": f"https://login.microsoftonline.com/{_TENANT}/v2.0",
        "tid": _TENANT,
        "aud": _CLIENT_ID,
        "sub": "sub-de-entra",
        "exp": int(time.time()) + 600,
        "nonce": _NONCE,
        "email": _VICTIMA,
        "name": "Quien Sea",
    }
    base.update(overrides)
    return base


class _Canje:
    """Cliente httpx simulado: el canje del código devuelve el token firmado."""

    id_token: ClassVar[str] = ""

    def __init__(self, **_kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _Canje:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def post(self, _url: str, **_kwargs: Any) -> Any:
        token = type(self).id_token

        class _Respuesta:
            status_code = 200

            @staticmethod
            def json() -> dict[str, str]:
                return {"id_token": token}

        return _Respuesta()


@pytest.fixture()
def entra(monkeypatch, clave_rsa):
    """Microsoft configurado, con su descubrimiento, su JWKS y el canje simulados."""
    numeros = clave_rsa.public_key().public_numbers()
    jwks = {
        "keys": [
            {
                "kid": "kid-de-prueba",
                "kty": "RSA",
                "n": _b64u_uint(numeros.n),
                "e": _b64u_uint(numeros.e),
            }
        ]
    }
    monkeypatch.setenv("OAUTH_MICROSOFT_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("OAUTH_MICROSOFT_CLIENT_SECRET", "microsoft-secret")
    monkeypatch.setenv("OAUTH_MICROSOFT_TENANT", "common")
    monkeypatch.setattr(identity, "_http_get_json", lambda _url: jwks)
    identity.reset_oidc_caches()
    monkeypatch.setattr(auth_routes, "fetch_discovery_document", lambda _url: dict(_DISCOVERY))
    monkeypatch.setattr(auth_routes, "verify_oauth_state", lambda _state: True)
    monkeypatch.setattr(auth_routes, "oauth_state_nonce", lambda _state: _NONCE)
    monkeypatch.setattr(auth_routes.httpx, "AsyncClient", _Canje)

    # La allowlist deja pasar el correo: lo que se prueba es que, aun así, un
    # correo sin acreditar no entra ni toca la cuenta de nadie.
    async def _permitido(_email: str) -> bool:
        return True

    monkeypatch.setattr(auth_routes, "_oauth_access_allowed", _permitido)

    def _callback(claims: dict[str, Any]) -> Response:
        _Canje.id_token = _firmar(clave_rsa, claims)
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/auth/oauth/microsoft/callback",
                "headers": [],
                "client": ("testclient", 50000),
            }
        )
        return asyncio.run(
            auth_routes.oauth_callback(
                provider="microsoft",
                code="code",
                state="state",
                response=Response(),
                request=request,
                pkce_verifier="verifier",
            )
        )

    return _callback


def _usuario(email: str) -> dict[str, Any]:
    from db.users import get_user_by_email

    usuario = get_user_by_email(email)
    assert usuario is not None
    return usuario


def _cuenta_de_google(email: str = _VICTIMA) -> int:
    from db.users import get_or_create_oauth_user

    return get_or_create_oauth_user(email=email, oauth_provider="google", oauth_sub="sub-de-google")


def _cuenta_local(email: str = _VICTIMA) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="hash-de-la-cuenta-local",  # pragma: allowlist secret
    )  # pragma: allowlist secret


# ── El callback de punta a punta ────────────────────────────────────────────


def test_un_token_de_entra_firmado_sin_correo_verificado_no_entra(tmp_db, entra):
    """El criterio del backlog: no entra y no altera el `oauth_sub` de la cuenta existente."""
    uid = _cuenta_de_google()

    resultado = entra(_claims_entra())  # sin `xms_edov`

    assert resultado.status_code == 302
    assert resultado.headers["location"].endswith("/login?error=oauth_failed")
    usuario = _usuario(_VICTIMA)
    assert usuario["id"] == uid
    assert (usuario["oauth_provider"], usuario["oauth_sub"]) == ("google", "sub-de-google")
    assert "session=" not in resultado.headers.get("set-cookie", "")


def test_sin_correo_verificado_tampoco_se_queda_con_una_cuenta_local(tmp_db, entra):
    uid = _cuenta_local()

    resultado = entra(_claims_entra(xms_edov=False))

    assert resultado.headers["location"].endswith("/login?error=oauth_failed")
    usuario = _usuario(_VICTIMA)
    assert usuario["id"] == uid
    assert usuario["oauth_provider"] is None
    assert usuario["password_hash"] == "hash-de-la-cuenta-local"  # pragma: allowlist secret


def test_con_correo_verificado_no_se_vincula_a_una_cuenta_de_google(tmp_db, entra):
    """Ni con `xms_edov`: un tenant de Entra no responde de una cuenta de Google."""
    _cuenta_de_google()

    resultado = entra(_claims_entra(xms_edov=True))

    assert resultado.headers["location"].endswith("/login?error=account_other_provider")
    usuario = _usuario(_VICTIMA)
    assert (usuario["oauth_provider"], usuario["oauth_sub"]) == ("google", "sub-de-google")


def test_con_correo_verificado_se_vincula_a_una_cuenta_local(tmp_db, entra):
    """El caso del ADR: el dueño del dominio acredita el buzón, como un enlace de reset."""
    uid = _cuenta_local()

    resultado = entra(_claims_entra(xms_edov=True))

    assert resultado.headers["location"].endswith("/resumen")
    usuario = _usuario(_VICTIMA)
    assert usuario["id"] == uid
    assert (usuario["oauth_provider"], usuario["oauth_sub"]) == ("microsoft", "sub-de-entra")


def test_el_correo_sale_de_email_y_no_de_preferred_username(tmp_db, entra):
    """Un `preferred_username` con la dirección de otro no abre su cuenta."""
    _cuenta_local()

    resultado = entra(
        _claims_entra(xms_edov=True, email="otra@empresa.test", preferred_username=_VICTIMA)
    )

    assert resultado.headers["location"].endswith("/resumen")
    assert _usuario(_VICTIMA)["oauth_provider"] is None
    assert _usuario("otra@empresa.test")["oauth_provider"] == "microsoft"


# ── La vinculación en `db/users.py` ─────────────────────────────────────────


def test_no_vincula_una_cuenta_de_otro_proveedor(tmp_db):
    from db.users import CuentaDeOtroProveedorError, get_or_create_oauth_user

    uid = _cuenta_de_google()

    with pytest.raises(CuentaDeOtroProveedorError) as error:
        get_or_create_oauth_user(email=_VICTIMA, oauth_provider="microsoft", oauth_sub="sub-ms")

    assert error.value.user_id == uid
    assert error.value.proveedor_existente == "google"
    assert _VICTIMA not in str(error.value)
    assert _usuario(_VICTIMA)["oauth_sub"] == "sub-de-google"


def test_regresion_google_sigue_vinculando_una_cuenta_local(tmp_db):
    from db.users import get_or_create_oauth_user

    uid = _cuenta_local()

    assert get_or_create_oauth_user(email=_VICTIMA, oauth_provider="google", oauth_sub="g") == uid
    assert _usuario(_VICTIMA)["oauth_provider"] == "google"


def test_regresion_mismo_proveedor_y_otro_sub_sigue_vinculando(tmp_db):
    from db.users import get_or_create_oauth_user

    uid = _cuenta_de_google()

    assert get_or_create_oauth_user(email=_VICTIMA, oauth_provider="google", oauth_sub="g2") == uid
    assert _usuario(_VICTIMA)["oauth_sub"] == "g2"
