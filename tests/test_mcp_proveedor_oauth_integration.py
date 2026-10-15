"""Proveedor OAuth del MCP contra Postgres: ``AlmacenOAuthPostgres`` y las reglas reales.

Lo que el unitario (``tests/test_mcp_proveedor_oauth.py``) fija con dobles se
comprueba aquí con lo de verdad, salvo Google: ``db/mcp_oauth.py`` como almacén,
``users`` para ``is_admin``/``deactivated_at``, ``access_grants`` para la
allowlist (con la mitad estática en «no», como en producción) y ``audit_log``
para la auditoría, que no debe contener ningún valor de token.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from db.access_grants import grant_access, revoke_access
from db.connection import connect_read
from db.mcp_oauth import hash_token
from db.users import create_user, deactivate_user, set_admin
from mcp_server.auth.google import IdentidadGoogle
from mcp_server.auth.proveedor import AlmacenOAuthPostgres, ProveedorTenderFlow

pytestmark = pytest.mark.anyio

REDIRECT = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


class GoogleFalso:
    def __init__(self) -> None:
        self.identidades = {
            "g-ana": IdentidadGoogle("Ana@Empresa.example", "1"),
            "g-luis": IdentidadGoogle("luis@empresa.example", "2"),
        }

    def url_autorizacion(self, state: str) -> str:
        return f"https://google.test/auth?state={state}"

    async def identidad(self, code: str, nonce: str) -> IdentidadGoogle | None:
        return self.identidades.get(code)


@pytest.fixture()
def admin(tmp_db: Any) -> Iterator[int]:
    user_id = create_user(
        email="ana@empresa.example", password_hash="x"
    )  # pragma: allowlist secret
    set_admin(user_id, True, granted_by="panel")
    no_admin = create_user(
        email="luis@empresa.example", password_hash="x"
    )  # pragma: allowlist secret
    for email in ("ana@empresa.example", "luis@empresa.example"):
        grant_access("email", email, granted_by=None)
    assert no_admin != user_id
    # Mitad estática en «no»: la allowlist la decide `access_grants`.
    with patch("services.access_grants.oauth_email_allowed", return_value=False):
        yield user_id


@pytest.fixture()
def proveedor(admin: int) -> ProveedorTenderFlow:
    return ProveedorTenderFlow(AlmacenOAuthPostgres(), GoogleFalso())


async def _cliente(proveedor: ProveedorTenderFlow) -> OAuthClientInformationFull:
    await proveedor.register_client(
        OAuthClientInformationFull(
            client_id="cliente-1",
            redirect_uris=[AnyUrl(REDIRECT)],
            token_endpoint_auth_method="none",
            scope="mcp",
        )
    )
    cliente = await proveedor.get_client("cliente-1")
    assert cliente is not None
    return cliente


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _login(
    proveedor: ProveedorTenderFlow, cliente: OAuthClientInformationFull, codigo_google: str
) -> dict[str, str]:
    params = AuthorizationParams(
        state="s",
        scopes=["mcp"],
        code_challenge="desafio",
        redirect_uri=AnyUrl(REDIRECT),
        redirect_uri_provided_explicitly=True,
        resource="https://mcp.example/mcp",
    )
    state = _query(await proveedor.authorize(cliente, params))["state"]
    return _query(await proveedor.completar_login(state, codigo_google, None))


async def _tokens(
    proveedor: ProveedorTenderFlow, cliente: OAuthClientInformationFull
) -> OAuthToken:
    q = await _login(proveedor, cliente, "g-ana")
    cargado = await proveedor.load_authorization_code(cliente, q["code"])
    assert cargado is not None and cargado.subject is not None
    return await proveedor.exchange_authorization_code(cliente, cargado)


def _auditoria() -> list[tuple[str, int | None, str]]:
    with connect_read() as c:
        filas = c.execute(
            "SELECT action, user_id, detail FROM audit_log WHERE action LIKE 'mcp.%%' ORDER BY id"
        ).fetchall()
    return [(f[0], f[1], f[2]) for f in filas]


async def test_flujo_completo_y_reutilizacion_contra_postgres(
    proveedor: ProveedorTenderFlow, admin: int
) -> None:
    cliente = await _cliente(proveedor)
    assert (await _login(proveedor, cliente, "g-luis")) == {"error": "access_denied", "state": "s"}

    t = await _tokens(proveedor, cliente)
    assert t.refresh_token is not None
    access = await proveedor.load_access_token(t.access_token)
    assert access is not None and access.subject == str(admin)

    cargado = await proveedor.load_refresh_token(cliente, t.refresh_token)
    assert cargado is not None
    rotado = await proveedor.exchange_refresh_token(cliente, cargado, ["mcp"])
    assert rotado.refresh_token is not None
    assert await proveedor.load_access_token(rotado.access_token) is not None

    # Reutilizar el refresh viejo revoca la familia entera en Postgres.
    assert await proveedor.load_refresh_token(cliente, t.refresh_token) is None
    assert await proveedor.load_access_token(rotado.access_token) is None
    assert await proveedor.load_refresh_token(cliente, rotado.refresh_token) is None

    acciones = [a for a, _, _ in _auditoria()]
    assert acciones == [
        "mcp.login_denegado",
        "mcp.login_ok",
        "mcp.token_emitido",
        "mcp.token_rotado",
        "mcp.refresh_reutilizado",
        # El refresh rotado, revocado con su familia, también se presenta:
        # `revoked_at` no distingue «consumido» de «revocado», y presentarlo se
        # trata (y audita) igual.
        "mcp.refresh_reutilizado",
    ]
    vista = json.dumps(_auditoria())
    for secreto in (t.access_token, t.refresh_token, rotado.access_token, rotado.refresh_token):
        assert secreto not in vista
        assert hash_token(secreto) not in vista
    denegado = json.loads(_auditoria()[0][2])
    assert denegado["motivo"] == "no_admin" and denegado["email"] == "luis@empresa.example"
    assert {uid for _, uid, _ in _auditoria()[1:]} == {admin}


@pytest.mark.parametrize("perdida", ["is_admin", "desactivado", "concesion"])
async def test_el_access_cae_al_perder_el_acceso(
    proveedor: ProveedorTenderFlow, admin: int, perdida: str
) -> None:
    cliente = await _cliente(proveedor)
    t = await _tokens(proveedor, cliente)
    assert await proveedor.load_access_token(t.access_token) is not None
    if perdida == "is_admin":
        set_admin(admin, False)
    elif perdida == "desactivado":
        deactivate_user(admin)
    else:
        with connect_read() as c:
            (grant_id,) = c.execute(
                "SELECT id FROM access_grants WHERE value = 'ana@empresa.example'"
            ).fetchone()
        revoke_access(grant_id)
    # Proveedor nuevo: sin la caché de 60 s del anterior.
    otro = ProveedorTenderFlow(AlmacenOAuthPostgres(), GoogleFalso())
    assert await otro.load_access_token(t.access_token) is None
