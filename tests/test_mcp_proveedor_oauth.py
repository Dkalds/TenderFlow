"""Proveedor OAuth 2.1 del MCP interno (``mcp_server/auth``), sin Postgres ni Google.

Qué se fija
-----------
- DCR solo acepta ``redirect_uris`` https o de loopback (``localhost`` /
  ``127.0.0.1``) en http.
- ``/authorize`` guarda la petición y manda a Google con un ``state`` firmado;
  el callback la consume una vez y solo emite código a un admin activo con
  acceso OAuth permitido. Cualquier otro vuelve al cliente con
  ``error=access_denied`` y su ``state`` original.
- Código de 60 s y un solo uso; access de 1 h; refresh de 30 días con rotación;
  reutilizar un refresh revoca la familia (también el access vigente).
- El access token cae en cuanto el usuario deja de ser admin (caché de 60 s).
- La auditoría registra lo que pasó sin un solo valor de token.

``AlmacenEnMemoria`` reproduce la semántica de ``db/mcp_oauth.py`` (familias,
revocación por reutilización) con el reloj inyectado para la caducidad. El
mismo flujo contra Postgres está en ``tests/test_mcp_proveedor_oauth_integration.py``,
y al final de este fichero pasa por los handlers reales del SDK.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationParams,
    AuthorizeError,
    IdentityAssertionParams,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from db.mcp_oauth import TipoToken, TokenNuevo, hash_token
from mcp_server.auth.google import ClienteGoogleReal, IdentidadGoogle
from mcp_server.auth.proveedor import AlmacenOAuth, ProveedorTenderFlow

pytestmark = pytest.mark.anyio

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
RESOURCE = "https://mcp.tenderflow.example/mcp"


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# Dobles
# ---------------------------------------------------------------------------


class Reloj:
    """Reloj inyectable: arranca en la hora real (el SDK compara con ``time.time``)."""

    def __init__(self) -> None:
        self.ahora = time.time()

    def __call__(self) -> float:
        return self.ahora

    def avanzar(self, segundos: float) -> None:
        self.ahora += segundos


class AlmacenEnMemoria:
    """Mismo contrato que ``db/mcp_oauth.py``; la caducidad se mide con el reloj inyectado."""

    def __init__(self, reloj: Callable[[], float]) -> None:
        self._reloj = reloj
        self.clientes: dict[str, dict[str, Any]] = {}
        self.tokens: dict[str, dict[str, Any]] = {}  # por sha256: nunca el token en claro

    def _ahora(self) -> datetime:
        return datetime.fromtimestamp(self._reloj(), UTC)

    def _vigente(self, fila: Mapping[str, Any]) -> bool:
        return fila["revoked_at"] is None and fila["expires_at"] > self._ahora()

    def _de(self, token: str, kind: TipoToken) -> dict[str, Any] | None:
        fila = self.tokens.get(hash_token(token))
        return fila if fila is not None and fila["kind"] == kind else None

    def guardar_cliente(
        self,
        client_id: str,
        client_name: str | None,
        redirect_uris: list[str],
        datos: Mapping[str, object],
    ) -> None:
        self.clientes[client_id] = {
            "client_id": client_id,
            "client_name": client_name,
            "redirect_uris": list(redirect_uris),
            "datos": json.loads(json.dumps(dict(datos))),
        }

    def obtener_cliente(self, client_id: str) -> dict[str, Any] | None:
        fila = self.clientes.get(client_id)
        return None if fila is None else dict(fila)

    def guardar_token(
        self,
        token: str,
        *,
        kind: TipoToken,
        client_id: str,
        user_id: int | None,
        family_id: str | None,
        scopes: list[str],
        datos: Mapping[str, object] | None,
        expires_at: datetime,
    ) -> None:
        assert expires_at.tzinfo is not None
        assert client_id in self.clientes  # la FK de verdad
        self.tokens[hash_token(token)] = {
            "token_hash": hash_token(token),
            "kind": kind,
            "client_id": client_id,
            "user_id": user_id,
            "family_id": family_id,
            "scopes": list(scopes),
            "datos": None if datos is None else json.loads(json.dumps(dict(datos))),
            "expires_at": expires_at,
            "revoked_at": None,
        }

    def obtener_token(self, token: str, kind: TipoToken) -> dict[str, Any] | None:
        fila = self._de(token, kind)
        return dict(fila) if fila is not None and self._vigente(fila) else None

    def buscar_token(self, token: str, kind: TipoToken) -> dict[str, Any] | None:
        fila = self._de(token, kind)
        return None if fila is None else dict(fila)

    def consumir_token(
        self, token: str, kind: Literal["pendiente"]
    ) -> tuple[dict[str, Any] | None, bool]:
        fila = self._de(token, kind)
        if fila is not None and self._vigente(fila):
            fila["revoked_at"] = self._ahora()
            return dict(fila), False
        return None, fila is not None and fila["revoked_at"] is not None

    def consumir_y_emitir(
        self,
        token: str,
        kind: Literal["code", "refresh"],
        nuevos: Sequence[TokenNuevo],
        *,
        family_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        if family_id is not None and kind != "code":
            raise ValueError("family_id solo se admite al canjear un code")
        fila = self._de(token, kind)
        if fila is None:
            return None, False
        if self._vigente(fila):
            fila["revoked_at"] = self._ahora()
            fila["family_id"] = family_id or fila["family_id"] or uuid.uuid4().hex
            for n in nuevos:
                self.guardar_token(
                    n.token,
                    kind=n.kind,
                    client_id=n.client_id,
                    user_id=n.user_id,
                    family_id=fila["family_id"],
                    scopes=n.scopes,
                    datos=n.datos,
                    expires_at=n.expires_at,
                )
            return dict(fila), False
        if fila["revoked_at"] is None:
            return None, False  # caducado sin consumir
        if fila["family_id"] is not None:
            self.revocar_familia(fila["family_id"])
        return dict(fila), True

    def revocar_familia(self, family_id: str) -> int:
        vivos = [
            f
            for f in self.tokens.values()
            if f["family_id"] == family_id and f["revoked_at"] is None
        ]
        for f in vivos:
            f["revoked_at"] = self._ahora()
        return len(vivos)

    def revocar_de_usuario(self, user_id: int) -> int:
        vivos = [
            f for f in self.tokens.values() if f["user_id"] == user_id and f["revoked_at"] is None
        ]
        for f in vivos:
            f["revoked_at"] = self._ahora()
        return len(vivos)

    def revocar_token(self, token: str) -> None:
        fila = self.tokens.get(hash_token(token))
        if fila is not None and fila["revoked_at"] is None:
            fila["revoked_at"] = self._ahora()


@dataclass
class GoogleFalso:
    """Google de pega: cada ``code`` conocido es una identidad verificada."""

    identidades: dict[str, IdentidadGoogle] = field(default_factory=dict)
    nonces: list[str] = field(default_factory=list)

    def url_autorizacion(self, state: str) -> str:
        return f"https://google.test/auth?state={state}"

    async def identidad(self, code: str, nonce: str) -> IdentidadGoogle | None:
        self.nonces.append(nonce)
        return self.identidades.get(code)


@dataclass
class Mundo:
    """Usuarios, allowlist y auditoría que ve el proveedor."""

    usuarios: dict[int, dict[str, Any]] = field(default_factory=dict)
    permitidos: set[str] = field(default_factory=set)
    auditoria: list[tuple[str, int | None, dict[str, object]]] = field(default_factory=list)

    def alta(self, user_id: int, email: str, *, admin: bool = True, activo: bool = True) -> None:
        self.usuarios[user_id] = {
            "id": user_id,
            "email": email,
            "is_admin": 1 if admin else 0,
            "deactivated_at": None if activo else datetime(2026, 1, 1, tzinfo=UTC),
        }
        self.permitidos.add(email.lower())

    def por_email(self, email: str) -> dict[str, Any] | None:
        for u in self.usuarios.values():
            if u["email"].lower() == email.lower() and u["deactivated_at"] is None:
                return dict(u)
        return None

    def por_id(self, user_id: int) -> dict[str, Any] | None:
        u = self.usuarios.get(user_id)
        return dict(u) if u is not None and u["deactivated_at"] is None else None

    def permitido(self, email: str) -> bool:
        return email.strip().lower() in self.permitidos

    def auditar(self, accion: str, user_id: int | None, detalle: Mapping[str, object]) -> None:
        self.auditoria.append((accion, user_id, dict(detalle)))

    def acciones(self) -> list[str]:
        return [a for a, _, _ in self.auditoria]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def reloj() -> Reloj:
    return Reloj()


@pytest.fixture()
def almacen(reloj: Reloj) -> AlmacenEnMemoria:
    return AlmacenEnMemoria(reloj)


@pytest.fixture()
def google() -> GoogleFalso:
    return GoogleFalso(
        {
            "g-ana": IdentidadGoogle(email="Ana@Empresa.ES", sub="1"),
            "g-luis": IdentidadGoogle(email="luis@empresa.es", sub="2"),
            "g-baja": IdentidadGoogle(email="baja@empresa.es", sub="3"),
            "g-ajena": IdentidadGoogle(email="ajena@empresa.es", sub="4"),
        }
    )


@pytest.fixture()
def mundo() -> Mundo:
    m = Mundo()
    m.alta(1, "ana@empresa.es")
    m.alta(2, "luis@empresa.es", admin=False)
    m.alta(3, "baja@empresa.es", activo=False)
    m.alta(4, "ajena@empresa.es")
    m.permitidos.discard("ajena@empresa.es")  # admin, pero fuera de la allowlist
    return m


@pytest.fixture()
def proveedor(
    almacen: AlmacenEnMemoria, google: GoogleFalso, mundo: Mundo, reloj: Reloj
) -> ProveedorTenderFlow:
    a: AlmacenOAuth = almacen  # el doble cumple el Protocol
    return ProveedorTenderFlow(
        a,
        google,
        usuarios=mundo.por_email,
        usuario_por_id=mundo.por_id,
        acceso_permitido=mundo.permitido,
        reloj=reloj,
        auditar=mundo.auditar,
    )


def _info(*redirects: str, client_id: str = "cliente-1") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        client_name="Claude",
        redirect_uris=[AnyUrl(r) for r in redirects],
        token_endpoint_auth_method="none",
        scope="mcp",
    )


@pytest.fixture()
async def cliente(proveedor: ProveedorTenderFlow) -> OAuthClientInformationFull:
    await proveedor.register_client(_info(REDIRECT))
    registrado = await proveedor.get_client("cliente-1")
    assert registrado is not None
    return registrado


def _params(state: str | None = "estado-del-cliente") -> AuthorizationParams:
    return AuthorizationParams(
        state=state,
        scopes=["mcp"],
        code_challenge="desafio-pkce",
        redirect_uri=AnyUrl(REDIRECT),
        redirect_uri_provided_explicitly=True,
        resource=RESOURCE,
    )


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


async def _login(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    codigo_google: str | None,
    *,
    error: str | None = None,
) -> dict[str, str]:
    url_google = await proveedor.authorize(cliente, _params())
    state = _query(url_google)["state"]
    vuelta = await proveedor.completar_login(state, codigo_google, error)
    assert vuelta.startswith(REDIRECT + "?")
    return _query(vuelta)


@pytest.fixture()
async def cliente_con_codigo(
    proveedor: ProveedorTenderFlow, cliente: OAuthClientInformationFull
) -> tuple[OAuthClientInformationFull, str]:
    q = await _login(proveedor, cliente, "g-ana")
    return cliente, q["code"]


@pytest.fixture()
async def tokens(
    proveedor: ProveedorTenderFlow,
    cliente_con_codigo: tuple[OAuthClientInformationFull, str],
) -> tuple[OAuthClientInformationFull, OAuthToken]:
    cliente, code = cliente_con_codigo
    cargado = await proveedor.load_authorization_code(cliente, code)
    assert cargado is not None
    return cliente, await proveedor.exchange_authorization_code(cliente, cargado)


async def _rotar(
    proveedor: ProveedorTenderFlow, cliente: OAuthClientInformationFull, refresh: str
) -> OAuthToken:
    cargado = await proveedor.load_refresh_token(cliente, refresh)
    assert cargado is not None
    return await proveedor.exchange_refresh_token(cliente, cargado, cargado.scopes)


# ---------------------------------------------------------------------------
# Registro dinámico (DCR)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "redirect",
    [
        "http://evil.com/cb",
        "http://localhost.evil.com/cb",
        "http://127.0.0.1.evil.com/cb",
        "http://localhost@evil.com/cb",
        "cursor://callback",
        "javascript:alert(1)",
        "https://claude.ai/cb#fragmento",
    ],
)
async def test_registro_rechaza_redirect_http_no_local(
    proveedor: ProveedorTenderFlow, almacen: AlmacenEnMemoria, redirect: str
) -> None:
    with pytest.raises(RegistrationError) as e:
        await proveedor.register_client(_info(REDIRECT, redirect))
    assert e.value.error == "invalid_redirect_uri"
    assert almacen.clientes == {}


async def test_registro_rechaza_sin_redirect_uris(proveedor: ProveedorTenderFlow) -> None:
    info = OAuthClientInformationFull(client_id="c", redirect_uris=None)
    with pytest.raises(RegistrationError):
        await proveedor.register_client(info)


async def test_registro_acepta_https_y_localhost(
    proveedor: ProveedorTenderFlow, almacen: AlmacenEnMemoria
) -> None:
    uris = (REDIRECT, "http://localhost:6274/oauth/callback", "http://127.0.0.1/cb")
    await proveedor.register_client(_info(*uris))
    assert almacen.clientes["cliente-1"]["redirect_uris"] == list(uris)
    leido = await proveedor.get_client("cliente-1")
    assert leido is not None
    assert [str(u) for u in leido.redirect_uris or []] == list(uris)
    assert leido.scope == "mcp" and leido.token_endpoint_auth_method == "none"
    assert await proveedor.get_client("no-existe") is None


# ---------------------------------------------------------------------------
# /authorize y callback de Google
# ---------------------------------------------------------------------------


async def test_authorize_redirige_a_google_con_state(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    almacen: AlmacenEnMemoria,
    reloj: Reloj,
) -> None:
    url = await proveedor.authorize(cliente, _params())
    assert url.startswith("https://google.test/auth?")
    state = _query(url)["state"]
    assert state != "estado-del-cliente"  # el state hacia Google es nuestro y firmado
    (pendiente,) = almacen.tokens.values()
    assert pendiente["kind"] == "pendiente" and pendiente["user_id"] is None
    assert pendiente["token_hash"] == hash_token(state.split(":")[0])
    assert pendiente["datos"]["state"] == "estado-del-cliente"
    assert pendiente["datos"]["code_challenge"] == "desafio-pkce"
    assert pendiente["expires_at"].timestamp() == pytest.approx(reloj() + 600)


async def test_login_admin_vuelve_con_codigo_y_state(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    google: GoogleFalso,
    mundo: Mundo,
) -> None:
    q = await _login(proveedor, cliente, "g-ana")
    assert set(q) == {"code", "state"}
    assert q["state"] == "estado-del-cliente"
    assert len(q["code"]) >= 43  # token_urlsafe(32): 256 bits
    assert len(google.nonces) == 1 and len(google.nonces[0]) == 32
    assert mundo.acciones() == ["mcp.login_ok"]


async def _afirma_denegado(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    almacen: AlmacenEnMemoria,
    mundo: Mundo,
    codigo_google: str | None,
    motivo: str,
    *,
    error: str | None = None,
) -> None:
    q = await _login(proveedor, cliente, codigo_google, error=error)
    assert q == {"error": "access_denied", "state": "estado-del-cliente"}
    assert [f["kind"] for f in almacen.tokens.values()] == ["pendiente"]  # ningún código
    accion, _, detalle = mundo.auditoria[-1]
    assert accion == "mcp.login_denegado"
    assert detalle["motivo"] == motivo


async def test_login_no_admin_vuelve_con_access_denied(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    almacen: AlmacenEnMemoria,
    mundo: Mundo,
) -> None:
    await _afirma_denegado(proveedor, cliente, almacen, mundo, "g-luis", "no_admin")


async def test_login_desactivado_vuelve_con_access_denied(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    almacen: AlmacenEnMemoria,
    mundo: Mundo,
) -> None:
    await _afirma_denegado(proveedor, cliente, almacen, mundo, "g-baja", "sin_usuario_activo")


async def test_login_fuera_de_allowlist_vuelve_con_access_denied(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    almacen: AlmacenEnMemoria,
    mundo: Mundo,
) -> None:
    await _afirma_denegado(proveedor, cliente, almacen, mundo, "g-ajena", "fuera_de_allowlist")


async def test_login_sin_identidad_o_con_error_de_google_vuelve_con_access_denied(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    almacen: AlmacenEnMemoria,
    mundo: Mundo,
) -> None:
    await _afirma_denegado(proveedor, cliente, almacen, mundo, "g-desconocido", "google")
    almacen.tokens.clear()
    await _afirma_denegado(
        proveedor, cliente, almacen, mundo, None, "google", error="access_denied"
    )


async def test_login_email_con_mayusculas_casa(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    almacen: AlmacenEnMemoria,
) -> None:
    q = await _login(proveedor, cliente, "g-ana")  # Google dice «Ana@Empresa.ES»
    codigo = almacen.tokens[hash_token(q["code"])]
    assert codigo["kind"] == "code" and codigo["user_id"] == 1


async def test_state_falsificado_lanza_authorize_error(proveedor: ProveedorTenderFlow) -> None:
    for state in ("", "abc", "0" * 32 + ":123:firma", "a:b:c"):
        with pytest.raises(AuthorizeError) as e:
            await proveedor.completar_login(state, "g-ana", None)
        assert e.value.error == "invalid_request"


async def test_state_valido_sin_peticion_pendiente_o_ya_usado_lanza_authorize_error(
    proveedor: ProveedorTenderFlow, cliente: OAuthClientInformationFull, reloj: Reloj
) -> None:
    from shared.auth_core import generate_oauth_state

    with pytest.raises(AuthorizeError):  # firmado, pero nadie pasó por /authorize
        await proveedor.completar_login(generate_oauth_state(), "g-ana", None)

    url = await proveedor.authorize(cliente, _params())
    state = _query(url)["state"]
    await proveedor.completar_login(state, "g-ana", None)
    with pytest.raises(AuthorizeError):  # el mismo callback dos veces
        await proveedor.completar_login(state, "g-ana", None)

    url = await proveedor.authorize(cliente, _params())
    reloj.avanzar(601)  # la petición pendiente vive 10 min
    with pytest.raises(AuthorizeError):
        await proveedor.completar_login(_query(url)["state"], "g-ana", None)


# ---------------------------------------------------------------------------
# Código de autorización
# ---------------------------------------------------------------------------


async def test_load_authorization_code_reconstruye_la_peticion(
    proveedor: ProveedorTenderFlow,
    cliente_con_codigo: tuple[OAuthClientInformationFull, str],
    reloj: Reloj,
) -> None:
    cliente, code = cliente_con_codigo
    cargado = await proveedor.load_authorization_code(cliente, code)
    assert cargado is not None
    assert cargado.code == code and cargado.client_id == "cliente-1"
    assert cargado.code_challenge == "desafio-pkce"
    assert str(cargado.redirect_uri) == REDIRECT
    assert cargado.redirect_uri_provided_explicitly is True
    assert cargado.resource == RESOURCE
    assert cargado.scopes == ["mcp"]
    assert cargado.subject == "1"
    assert cargado.expires_at == pytest.approx(reloj() + 60)


async def test_codigo_de_otro_cliente_no_existe(
    proveedor: ProveedorTenderFlow,
    cliente_con_codigo: tuple[OAuthClientInformationFull, str],
) -> None:
    _, code = cliente_con_codigo
    await proveedor.register_client(_info(REDIRECT, client_id="cliente-2"))
    otro = await proveedor.get_client("cliente-2")
    assert otro is not None
    assert await proveedor.load_authorization_code(otro, code) is None


async def test_codigo_de_un_solo_uso(
    proveedor: ProveedorTenderFlow,
    cliente_con_codigo: tuple[OAuthClientInformationFull, str],
    mundo: Mundo,
) -> None:
    cliente, code = cliente_con_codigo
    cargado = await proveedor.load_authorization_code(cliente, code)
    assert cargado is not None
    primero = await proveedor.exchange_authorization_code(cliente, cargado)
    assert primero.token_type == "Bearer" and primero.expires_in == 3600
    assert primero.refresh_token and primero.scope == "mcp"
    assert await proveedor.load_authorization_code(cliente, code) is None
    with pytest.raises(TokenError) as e:  # dos canjes en vuelo con el mismo código cargado
        await proveedor.exchange_authorization_code(cliente, cargado)
    assert e.value.error == "invalid_grant"
    # Reutilizar el código revoca lo que emitió.
    assert await proveedor.load_access_token(primero.access_token) is None
    assert "mcp.codigo_reutilizado" in mundo.acciones()


async def test_codigo_caduca_a_los_60s(
    proveedor: ProveedorTenderFlow,
    cliente_con_codigo: tuple[OAuthClientInformationFull, str],
    reloj: Reloj,
) -> None:
    cliente, code = cliente_con_codigo
    reloj.avanzar(59)
    cargado = await proveedor.load_authorization_code(cliente, code)
    assert cargado is not None
    reloj.avanzar(2)
    assert await proveedor.load_authorization_code(cliente, code) is None
    with pytest.raises(TokenError) as e:
        await proveedor.exchange_authorization_code(cliente, cargado)
    assert e.value.error == "invalid_grant"


async def test_el_canje_vuelve_a_mirar_si_sigue_siendo_admin(
    proveedor: ProveedorTenderFlow,
    cliente_con_codigo: tuple[OAuthClientInformationFull, str],
    mundo: Mundo,
) -> None:
    cliente, code = cliente_con_codigo
    cargado = await proveedor.load_authorization_code(cliente, code)
    assert cargado is not None
    mundo.usuarios[1]["is_admin"] = 0
    with pytest.raises(TokenError) as e:
        await proveedor.exchange_authorization_code(cliente, cargado)
    assert e.value.error == "invalid_grant"


# ---------------------------------------------------------------------------
# Access y refresh
# ---------------------------------------------------------------------------


async def test_access_token_valido(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    reloj: Reloj,
) -> None:
    _, t = tokens
    access = await proveedor.load_access_token(t.access_token)
    assert isinstance(access, AccessToken)
    assert access.client_id == "cliente-1" and access.subject == "1"
    assert access.scopes == ["mcp"] and access.resource == RESOURCE
    assert access.expires_at == int(reloj() + 3600)
    assert await proveedor.load_access_token("inventado") is None
    assert t.refresh_token is not None
    assert await proveedor.load_access_token(t.refresh_token) is None  # un refresh no es access


async def test_refresh_rota_y_el_viejo_no_vale(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    almacen: AlmacenEnMemoria,
    reloj: Reloj,
    mundo: Mundo,
) -> None:
    cliente, t = tokens
    assert t.refresh_token is not None
    cargado = await proveedor.load_refresh_token(cliente, t.refresh_token)
    assert isinstance(cargado, RefreshToken)
    assert cargado.subject == "1" and cargado.resource == RESOURCE
    assert cargado.expires_at == int(reloj() + 30 * 86400)
    nuevo = await proveedor.exchange_refresh_token(cliente, cargado, ["mcp"])
    assert nuevo.refresh_token and nuevo.refresh_token != t.refresh_token
    assert nuevo.access_token != t.access_token
    assert await proveedor.load_access_token(nuevo.access_token) is not None
    viejo = almacen.tokens[hash_token(t.refresh_token)]
    assert viejo["revoked_at"] is not None
    assert almacen.tokens[hash_token(nuevo.refresh_token)]["family_id"] == viejo["family_id"]
    assert "mcp.token_rotado" in mundo.acciones()
    # El viejo ya no se canjea (y presentarlo es una reutilización).
    assert await proveedor.load_refresh_token(cliente, t.refresh_token) is None
    with pytest.raises(TokenError) as e:  # dos canjes en vuelo con el mismo refresh cargado
        await proveedor.exchange_refresh_token(cliente, cargado, ["mcp"])
    assert e.value.error == "invalid_grant"


async def test_refresh_reutilizado_revoca_familia(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    mundo: Mundo,
) -> None:
    cliente, t = tokens
    assert t.refresh_token is not None
    rotado = await _rotar(proveedor, cliente, t.refresh_token)
    assert rotado.refresh_token is not None
    assert await proveedor.load_access_token(rotado.access_token) is not None

    assert await proveedor.load_refresh_token(cliente, t.refresh_token) is None  # reutilización
    assert await proveedor.load_access_token(rotado.access_token) is None
    assert await proveedor.load_access_token(t.access_token) is None
    assert await proveedor.load_refresh_token(cliente, rotado.refresh_token) is None
    assert "mcp.refresh_reutilizado" in mundo.acciones()


async def test_refresh_de_otro_cliente_o_desconocido_no_existe(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
) -> None:
    cliente, t = tokens
    assert t.refresh_token is not None
    await proveedor.register_client(_info(REDIRECT, client_id="cliente-2"))
    otro = await proveedor.get_client("cliente-2")
    assert otro is not None
    assert await proveedor.load_refresh_token(otro, t.refresh_token) is None
    assert await proveedor.load_refresh_token(cliente, "inventado") is None
    assert await proveedor.load_refresh_token(cliente, t.access_token) is None
    # Nada de eso tocó la familia legítima.
    assert await proveedor.load_access_token(t.access_token) is not None
    assert await proveedor.load_refresh_token(cliente, t.refresh_token) is not None


async def test_refresh_caduca_a_los_30_dias(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    reloj: Reloj,
) -> None:
    cliente, t = tokens
    assert t.refresh_token is not None
    reloj.avanzar(30 * 86400 + 1)
    assert await proveedor.load_refresh_token(cliente, t.refresh_token) is None


async def test_refresh_no_se_concede_a_quien_dejo_de_ser_admin(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    mundo: Mundo,
    reloj: Reloj,
) -> None:
    cliente, t = tokens
    assert t.refresh_token is not None
    mundo.usuarios[1]["is_admin"] = 0
    reloj.avanzar(61)
    assert await proveedor.load_refresh_token(cliente, t.refresh_token) is None


async def test_access_token_cae_al_perder_admin(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    mundo: Mundo,
    reloj: Reloj,
) -> None:
    _, t = tokens
    assert await proveedor.load_access_token(t.access_token) is not None
    mundo.usuarios[1]["is_admin"] = 0
    reloj.avanzar(30)
    assert await proveedor.load_access_token(t.access_token) is not None  # caché de 60 s
    reloj.avanzar(31)
    assert await proveedor.load_access_token(t.access_token) is None


@pytest.mark.parametrize("perdida", ["desactivado", "fuera_de_allowlist"])
async def test_access_token_cae_al_desactivar_o_salir_de_la_allowlist(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    mundo: Mundo,
    reloj: Reloj,
    perdida: str,
) -> None:
    _, t = tokens
    assert await proveedor.load_access_token(t.access_token) is not None
    if perdida == "desactivado":
        mundo.usuarios[1]["deactivated_at"] = datetime(2026, 10, 1, tzinfo=UTC)
    else:
        mundo.permitidos.discard("ana@empresa.es")
    reloj.avanzar(61)
    assert await proveedor.load_access_token(t.access_token) is None


async def test_access_token_caduca_en_1h(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    reloj: Reloj,
) -> None:
    _, t = tokens
    reloj.avanzar(3599)
    assert await proveedor.load_access_token(t.access_token) is not None
    reloj.avanzar(2)
    assert await proveedor.load_access_token(t.access_token) is None


async def test_revocar_un_token_revoca_su_familia(
    proveedor: ProveedorTenderFlow,
    tokens: tuple[OAuthClientInformationFull, OAuthToken],
    mundo: Mundo,
) -> None:
    cliente, t = tokens
    assert t.refresh_token is not None
    access = await proveedor.load_access_token(t.access_token)
    assert access is not None
    await proveedor.revoke_token(access)
    assert await proveedor.load_access_token(t.access_token) is None
    assert await proveedor.load_refresh_token(cliente, t.refresh_token) is None
    assert "mcp.token_revocado" in mundo.acciones()


async def test_identity_assertion_no_soportado(
    proveedor: ProveedorTenderFlow, cliente: OAuthClientInformationFull
) -> None:
    with pytest.raises(TokenError) as e:
        await proveedor.exchange_identity_assertion(
            cliente, IdentityAssertionParams(assertion="x.y.z")
        )
    assert e.value.error == "unsupported_grant_type"


async def test_audita_login_denegado_y_reutilizacion(
    proveedor: ProveedorTenderFlow,
    cliente: OAuthClientInformationFull,
    almacen: AlmacenEnMemoria,
    mundo: Mundo,
) -> None:
    await _login(proveedor, cliente, "g-luis")
    q = await _login(proveedor, cliente, "g-ana")
    cargado = await proveedor.load_authorization_code(cliente, q["code"])
    assert cargado is not None
    t = await proveedor.exchange_authorization_code(cliente, cargado)
    assert t.refresh_token is not None
    rotado = await _rotar(proveedor, cliente, t.refresh_token)
    assert await proveedor.load_refresh_token(cliente, t.refresh_token) is None

    assert mundo.acciones() == [
        "mcp.login_denegado",
        "mcp.login_ok",
        "mcp.token_emitido",
        "mcp.token_rotado",
        "mcp.refresh_reutilizado",
    ]
    denegado = mundo.auditoria[0]
    assert denegado[1] is None
    assert denegado[2]["motivo"] == "no_admin" and denegado[2]["email"] == "luis@empresa.es"
    assert {uid for _, uid, _ in mundo.auditoria[1:]} == {1}
    familia = almacen.tokens[hash_token(t.refresh_token)]["family_id"]
    assert mundo.auditoria[-1][2]["family_id"] == familia

    vista = json.dumps(mundo.auditoria, default=str)
    assert rotado.refresh_token is not None
    secretos = [q["code"], t.access_token, t.refresh_token, rotado.access_token]
    secretos += [rotado.refresh_token, *(f["token_hash"] for f in almacen.tokens.values())]
    for secreto in secretos:
        assert secreto not in vista


# ---------------------------------------------------------------------------
# auditar_oauth y el adaptador de Postgres
# ---------------------------------------------------------------------------


def test_auditar_oauth_escribe_en_audit_log(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_server.auth import proveedor as modulo

    llamadas: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(modulo, "log_action", lambda *a, **k: llamadas.append((a, k)))
    modulo.auditar_oauth("mcp.login_ok", 7, {"client_id": "c", "ñ": "sí"})
    modulo.auditar_oauth("mcp.login_denegado", None, {"motivo": "no_admin"})
    assert llamadas[0] == (
        ("user:7", "mcp", "mcp.login_ok", '{"client_id": "c", "ñ": "sí"}'),
        {"user_id": 7},
    )
    assert llamadas[1][0][0] == "anon" and llamadas[1][1] == {"user_id": None}


def test_almacen_postgres_delega_en_db_mcp_oauth() -> None:
    import inspect

    import db.mcp_oauth as db_oauth
    from mcp_server.auth.proveedor import AlmacenOAuthPostgres

    metodos = [
        "guardar_cliente",
        "obtener_cliente",
        "guardar_token",
        "obtener_token",
        "buscar_token",
        "consumir_token",
        "consumir_y_emitir",
        "revocar_familia",
        "revocar_de_usuario",
        "revocar_token",
    ]

    def _firma(f: Any, *, sin_self: bool = False) -> list[tuple[str, Any, Any]]:
        params = list(inspect.signature(f).parameters.values())[1 if sin_self else 0 :]
        return [(p.name, p.kind, p.default) for p in params]

    almacen: AlmacenOAuth = AlmacenOAuthPostgres()  # mypy: cumple el Protocol
    for nombre in metodos:
        original = _firma(getattr(db_oauth, nombre))
        assert _firma(getattr(AlmacenOAuth, nombre), sin_self=True) == original, nombre
        assert _firma(getattr(almacen, nombre)) == original, nombre
        assert getattr(almacen, nombre) is getattr(db_oauth, nombre), nombre


# ---------------------------------------------------------------------------
# ClienteGoogleReal (red simulada con httpx.MockTransport)
# ---------------------------------------------------------------------------


@pytest.fixture()
def google_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "id-google.apps.example")
    monkeypatch.setenv(
        "MCP_GOOGLE_REDIRECT_URI", "https://mcp.tenderflow.example/oauth/google/callback"
    )


def test_url_de_google(google_config: None) -> None:
    from shared.auth_core import generate_oauth_state

    state = generate_oauth_state()
    url = ClienteGoogleReal().url_autorizacion(state)
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    q = _query(url)
    assert q == {
        "client_id": "id-google.apps.example",
        "redirect_uri": "https://mcp.tenderflow.example/oauth/google/callback",
        "response_type": "code",
        "scope": "openid email",
        "state": state,
        "nonce": state.split(":")[0],
        "prompt": "select_account",
        "access_type": "online",
    }


def _cliente_google(
    respuesta: httpx.Response, claims: dict[str, object] | None, vistos: list[Any]
) -> ClienteGoogleReal:
    def _manejar(peticion: httpx.Request) -> httpx.Response:
        vistos.append(dict(parse_qs(peticion.content.decode())))
        vistos.append(str(peticion.url))
        return respuesta

    def _verificar(jwt: str, *, audience: str, expected_nonce: str | None = None) -> Any:
        vistos.append((jwt, audience, expected_nonce))
        return claims

    return ClienteGoogleReal(transport=httpx.MockTransport(_manejar), verificar=_verificar)


async def test_identidad_de_google(google_config: None) -> None:
    vistos: list[Any] = []
    claims: dict[str, object] = {"email": " Ana@Empresa.ES ", "sub": "42", "email_verified": True}
    g = _cliente_google(httpx.Response(200, json={"id_token": "jwt"}), claims, vistos)
    assert await g.identidad("codigo", "n" * 32) == IdentidadGoogle("Ana@Empresa.ES", "42")
    form, url, verificado = vistos
    assert url == "https://oauth2.googleapis.com/token"
    assert form["code"] == ["codigo"] and form["grant_type"] == ["authorization_code"]
    assert form["redirect_uri"] == ["https://mcp.tenderflow.example/oauth/google/callback"]
    assert verificado == ("jwt", "id-google.apps.example", "n" * 32)


@pytest.mark.parametrize(
    ("respuesta", "claims"),
    [
        (httpx.Response(400, json={"error": "invalid_grant"}), {"email": "a@b.es", "sub": "1"}),
        (httpx.Response(200, json={}), {"email": "a@b.es", "sub": "1"}),
        (httpx.Response(200, json={"id_token": "jwt"}), None),
        (
            httpx.Response(200, json={"id_token": "jwt"}),
            {"email": "a@b.es", "sub": "1", "email_verified": False},
        ),
        (
            httpx.Response(200, json={"id_token": "jwt"}),
            {"email": "x@evil.com@b.es", "sub": "1", "email_verified": True},
        ),
        (httpx.Response(200, json={"id_token": "jwt"}), {"sub": "1", "email_verified": True}),
    ],
)
async def test_identidad_de_google_rechaza(
    google_config: None, respuesta: httpx.Response, claims: dict[str, object] | None
) -> None:
    g = _cliente_google(respuesta, claims, [])
    assert await g.identidad("codigo", "n" * 32) is None


async def test_identidad_de_google_sin_red(google_config: None) -> None:
    def _caida(_peticion: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    g = ClienteGoogleReal(transport=httpx.MockTransport(_caida))
    assert await g.identidad("codigo", "n" * 32) is None


# ---------------------------------------------------------------------------
# Extremo a extremo por los handlers reales del SDK
# ---------------------------------------------------------------------------


def _pkce() -> tuple[str, str]:
    verifier = "v" * 64
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _codigo_por_el_sdk(
    http: httpx.AsyncClient, proveedor: ProveedorTenderFlow, client_id: str, challenge: str
) -> str:
    """``GET /authorize`` del SDK y el callback de Google; devuelve el código emitido."""
    r = await http.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "estado-del-cliente",
            "resource": RESOURCE,
        },
    )
    assert r.status_code == 302, r.text
    state = _query(r.headers["location"])["state"]
    q = _query(await proveedor.completar_login(state, "g-ana", None))
    assert q["state"] == "estado-del-cliente"
    return q["code"]


async def test_flujo_completo_por_los_handlers_del_sdk(
    proveedor: ProveedorTenderFlow, mundo: Mundo
) -> None:
    """``/register`` → ``/authorize`` → callback → ``/token`` (código y refresh) con el SDK."""
    from mcp.server.auth.routes import create_auth_routes
    from mcp.server.auth.settings import ClientRegistrationOptions
    from pydantic import AnyHttpUrl
    from starlette.applications import Starlette

    rutas = create_auth_routes(
        proveedor,
        AnyHttpUrl("https://mcp.tenderflow.example"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=["mcp"], default_scopes=["mcp"]
        ),
    )
    transporte = httpx.ASGITransport(app=Starlette(routes=rutas))
    async with httpx.AsyncClient(
        transport=transporte, base_url="https://mcp.tenderflow.example"
    ) as http:
        r = await http.post(
            "/register",
            json={"redirect_uris": ["http://evil.com/cb"], "token_endpoint_auth_method": "none"},
        )
        assert r.status_code == 400 and r.json()["error"] == "invalid_redirect_uri"
        r = await http.post(
            "/register", json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none"}
        )
        assert r.status_code == 201, r.text
        client_id = r.json()["client_id"]
        verifier, challenge = _pkce()

        canje = {
            "grant_type": "authorization_code",
            "code": await _codigo_por_el_sdk(http, proveedor, client_id, challenge),
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": "otro-" + verifier,
        }
        r = await http.post("/token", data=canje)
        assert r.status_code == 400 and r.json()["error"] == "invalid_grant"  # PKCE
        canje["code_verifier"] = verifier
        r = await http.post("/token", data=canje)
        assert r.status_code == 200, r.text
        t = r.json()
        assert t["token_type"] == "Bearer" and t["expires_in"] == 3600 and t["scope"] == "mcp"
        r = await http.post("/token", data=canje)
        assert r.status_code == 400 and r.json()["error"] == "invalid_grant"  # un solo uso
        # Reutilizar el código revocó lo que emitió: se vuelve a empezar.
        assert await proveedor.load_access_token(t["access_token"]) is None

        canje["code"] = await _codigo_por_el_sdk(http, proveedor, client_id, challenge)
        t = (await http.post("/token", data=canje)).json()
        rotacion = {
            "grant_type": "refresh_token",
            "refresh_token": t["refresh_token"],
            "client_id": client_id,
        }
        r = await http.post("/token", data=rotacion)
        assert r.status_code == 200, r.text
        t2 = r.json()
        assert t2["refresh_token"] != t["refresh_token"]
        assert await proveedor.load_access_token(t2["access_token"]) is not None
        r = await http.post("/token", data=rotacion)  # el refresh viejo otra vez
        assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
        assert await proveedor.load_access_token(t2["access_token"]) is None
    assert mundo.acciones().count("mcp.refresh_reutilizado") == 1
