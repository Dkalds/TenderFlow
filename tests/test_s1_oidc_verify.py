"""Verificación genérica de ``id_token`` OIDC (``shared.identity``).

Se firma un JWT de verdad con una clave RSA efímera y se sirve su JWK desde un
JWKS simulado: sin eso, el test comprobaría la lógica de claims pero no que la
firma se verifica realmente, que es la única parte que impide aceptar un token
fabricado.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from shared import identity

_ISSUER_MULTITENANT = "https://login.microsoftonline.com/{tenantid}/v2.0"
_TENANT = "11111111-2222-3333-4444-555555555555"
_AUDIENCE = "client-id-de-prueba"
_JWKS_URI = "https://login.microsoftonline.com/common/discovery/v2.0/keys"


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_json(data: dict[str, Any]) -> str:
    return _b64u(json.dumps(data, separators=(",", ":")).encode("utf-8"))


def _b64u_uint(value: int) -> str:
    return _b64u(value.to_bytes((value.bit_length() + 7) // 8, "big"))


@pytest.fixture()
def clave_rsa() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def jwks_simulado(monkeypatch, clave_rsa) -> None:
    """Sirve el JWK de la clave efímera en vez de salir a la red."""
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
    monkeypatch.setattr(identity, "_http_get_json", lambda _url: jwks)
    identity.reset_oidc_caches()


def _firmar(clave: rsa.RSAPrivateKey, claims: dict[str, Any], *, kid: str = "kid-de-prueba") -> str:
    header = _b64u_json({"alg": "RS256", "kid": kid, "typ": "JWT"})
    cuerpo = _b64u_json(claims)
    firma = clave.sign(
        f"{header}.{cuerpo}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return f"{header}.{cuerpo}.{_b64u(firma)}"


def _claims(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "iss": f"https://login.microsoftonline.com/{_TENANT}/v2.0",
        "tid": _TENANT,
        "aud": _AUDIENCE,
        "sub": "sub-de-prueba",
        "exp": int(time.time()) + 600,
        "nonce": "nonce-de-prueba",
        "preferred_username": "persona@empresa.test",
    }
    base.update(overrides)
    return base


def _verificar(token: str) -> dict[str, Any] | None:
    return identity.verify_oidc_id_token(
        token,
        jwks_uri=_JWKS_URI,
        issuer=_ISSUER_MULTITENANT,
        audience=_AUDIENCE,
        expected_nonce="nonce-de-prueba",
    )


def test_acepta_un_token_bien_firmado_de_un_tenant_cualquiera(clave_rsa, jwks_simulado):
    claims = _verificar(_firmar(clave_rsa, _claims()))

    assert claims is not None
    assert claims["preferred_username"] == "persona@empresa.test"


def test_rechaza_una_firma_de_otra_clave(clave_rsa, jwks_simulado):
    intrusa = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    assert _verificar(_firmar(intrusa, _claims())) is None


def test_rechaza_un_issuer_que_no_corresponde_al_tid(clave_rsa, jwks_simulado):
    # La plantilla `{tenantid}` se rellena con el `tid` del token: un emisor de
    # otro tenant no puede colarse solo porque «se parezca».
    token = _firmar(clave_rsa, _claims(iss="https://login.microsoftonline.com/otro/v2.0"))

    assert _verificar(token) is None


def test_rechaza_una_audiencia_ajena(clave_rsa, jwks_simulado):
    assert _verificar(_firmar(clave_rsa, _claims(aud="otra-aplicacion"))) is None


def test_rechaza_un_nonce_distinto(clave_rsa, jwks_simulado):
    assert _verificar(_firmar(clave_rsa, _claims(nonce="otro"))) is None


def test_rechaza_un_token_caducado(clave_rsa, jwks_simulado):
    assert _verificar(_firmar(clave_rsa, _claims(exp=int(time.time()) - 3600))) is None


def test_rechaza_un_kid_desconocido(clave_rsa, jwks_simulado):
    assert _verificar(_firmar(clave_rsa, _claims(), kid="kid-que-no-existe")) is None


def test_el_documento_de_descubrimiento_se_cachea(monkeypatch):
    """Una llamada por TTL: si no, cada login saldría a la red del proveedor."""
    llamadas: list[str] = []

    def _fake(url: str) -> dict[str, Any]:
        llamadas.append(url)
        return {"issuer": "https://ejemplo.test", "jwks_uri": "https://ejemplo.test/keys"}

    identity.reset_oidc_caches()
    monkeypatch.setattr(identity, "_http_get_json", _fake)

    primero = identity.fetch_discovery_document("https://ejemplo.test/.well-known/x")
    segundo = identity.fetch_discovery_document("https://ejemplo.test/.well-known/x")

    assert primero == segundo
    assert llamadas == ["https://ejemplo.test/.well-known/x"]
