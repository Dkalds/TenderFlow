"""Servidor de autorización OAuth 2.1 del MCP interno (``mcp.server.auth``).

El MCP es su propio Authorization Server, como exige la especificación MCP
para los conectores de claude.ai, y delega la identidad en Google. Solo un
administrador activo de TenderFlow con acceso OAuth permitido obtiene tokens.

Cómo lo maneja el SDK (``mcp==2.3.0``)
--------------------------------------
- ``/register`` (DCR) → :meth:`ProveedorTenderFlow.register_client`.
- ``/authorize`` → :meth:`~ProveedorTenderFlow.authorize`: guarda la petición
  (``pendiente``, 10 min) y manda a Google. Google vuelve a nuestro callback,
  que llama a :meth:`~ProveedorTenderFlow.completar_login` (no es parte del
  protocolo del SDK; la ruta la monta el servidor).
- ``/token`` con ``authorization_code``: el SDK llama a
  ``load_authorization_code``, comprueba él mismo caducidad, cliente,
  ``redirect_uri`` y PKCE, y luego ``exchange_authorization_code``.
- ``/token`` con ``refresh_token``: ``load_refresh_token`` (aquí se detecta
  la reutilización) y ``exchange_refresh_token``.
- Cada petición a ``/mcp``: ``load_access_token``, que vuelve a mirar si el
  usuario sigue siendo admin (caché de 60 s).
- ``/revoke``: ``load_access_token``/``load_refresh_token`` y ``revoke_token``.

Tokens opacos (``secrets.token_urlsafe(32)``); solo su ``sha256`` llega a la base
(``db/mcp_oauth.py``). Ningún valor de token se audita ni se registra.
"""

from __future__ import annotations

import functools
import json
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal, ParamSpec, Protocol, TypeVar
from urllib.parse import urlsplit

import anyio.to_thread
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    IdentityAssertionParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from config.settings import mcp_redirect_uris_extra
from db import mcp_oauth
from db.audit import log_action
from db.mcp_oauth import TipoToken, TokenNuevo
from db.users import get_active_user_by_email_ci, get_user_by_id
from mcp_server.auth.google import ClienteGoogle
from observability.logging import get_logger
from services.access_grants import acceso_oauth_permitido
from shared.auth_core import generate_oauth_state, oauth_state_nonce, verify_oauth_state

__all__ = [
    "REDIRECTS_CLAUDE",
    "AlmacenOAuth",
    "AlmacenOAuthPostgres",
    "ProveedorTenderFlow",
    "auditar_oauth",
    "redirect_uri_admitido",
]

log = get_logger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

#: Vidas (segundos), de las Global Constraints.
TTL_PENDIENTE = 600
TTL_CODIGO = 60
TTL_ACCESS = 3600
TTL_REFRESH = 30 * 86400
#: Cuánto vale la última comprobación de «sigue siendo admin» de un usuario.
CACHE_ADMIN = 60

_LOOPBACK = frozenset({"localhost", "127.0.0.1"})
#: Callbacks documentados de Anthropic para conectores MCP (claude.ai / claude.com).
REDIRECTS_CLAUDE = (
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
)
_FORMAS_ADMITIDAS = (
    "redirect_uris admitidos: "
    + ", ".join(REDIRECTS_CLAUDE)
    + ", http://localhost[:puerto]/… y http://127.0.0.1[:puerto]/…"
    + " y los configurados en MCP_REDIRECT_URIS_EXTRA."
)


# ---------------------------------------------------------------------------
# Almacén
# ---------------------------------------------------------------------------


class AlmacenOAuth(Protocol):
    """La persistencia que usa el proveedor: el contrato de ``db/mcp_oauth.py``.

    Mismos nombres y firmas; los tests lo cumplen con un almacén en memoria.
    """

    def guardar_cliente(
        self,
        client_id: str,
        client_name: str | None,
        redirect_uris: list[str],
        datos: Mapping[str, object],
    ) -> None: ...

    def obtener_cliente(self, client_id: str) -> dict[str, Any] | None: ...

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
    ) -> None: ...

    def obtener_token(self, token: str, kind: TipoToken) -> dict[str, Any] | None: ...

    def buscar_token(self, token: str, kind: TipoToken) -> dict[str, Any] | None: ...

    def consumir_token(
        self, token: str, kind: Literal["pendiente"]
    ) -> tuple[dict[str, Any] | None, bool]: ...

    def consumir_y_emitir(
        self,
        token: str,
        kind: Literal["code", "refresh"],
        nuevos: Sequence[TokenNuevo],
        *,
        family_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, bool]: ...

    def revocar_familia(self, family_id: str) -> int: ...

    def revocar_de_usuario(self, user_id: int) -> int: ...

    def revocar_token(self, token: str) -> None: ...


class AlmacenOAuthPostgres:
    """:class:`AlmacenOAuth` sobre Postgres: las funciones de ``db/mcp_oauth.py`` tal cual."""

    guardar_cliente = staticmethod(mcp_oauth.guardar_cliente)
    obtener_cliente = staticmethod(mcp_oauth.obtener_cliente)
    guardar_token = staticmethod(mcp_oauth.guardar_token)
    obtener_token = staticmethod(mcp_oauth.obtener_token)
    buscar_token = staticmethod(mcp_oauth.buscar_token)
    consumir_token = staticmethod(mcp_oauth.consumir_token)
    consumir_y_emitir = staticmethod(mcp_oauth.consumir_y_emitir)
    revocar_familia = staticmethod(mcp_oauth.revocar_familia)
    revocar_de_usuario = staticmethod(mcp_oauth.revocar_de_usuario)
    revocar_token = staticmethod(mcp_oauth.revocar_token)


# ---------------------------------------------------------------------------
# Auditoría y validaciones
# ---------------------------------------------------------------------------


def auditar_oauth(accion: str, user_id: int | None, detalle: Mapping[str, object]) -> None:
    """Escribe ``accion`` en ``audit_log`` (``db.audit.log_action``, que no lanza).

    Es la **única** llamada a ``log_action`` del MCP: la auditoría OAuth de este
    módulo y la de las llamadas a tools (Task 8) pasan por aquí.

    ``detalle`` nunca lleva el valor de un token: solo cliente, familia, motivo
    y, en un login denegado, el correo que lo intentó.
    """
    # El primer argumento posicional de `log_action` es la clave opaca que
    # persigue el ratchet de identidad de `scripts/` (D18). Aquí vale `"user:{id}"` (o
    # `"anon"`), derivada del id y NO del correo, así que no amplía esa deuda; va
    # en posición para no nombrar el parámetro en un fichero nuevo.
    clave = f"user:{user_id}" if user_id is not None else "anon"
    log_action(clave, "mcp", accion, json.dumps(dict(detalle), ensure_ascii=False), user_id=user_id)


def _es_loopback(uri: str) -> bool:
    """``http://localhost`` o ``http://127.0.0.1``, con cualquier puerto y ruta, sin fragmento.

    Compara el host ya parseado: ``http://localhost@evil.com/`` o
    ``http://localhost.evil.com/`` no pasan.
    """
    try:
        partes = urlsplit(uri)
        host = partes.hostname
        partes.port  # noqa: B018 — un puerto inválido lanza ValueError
    except ValueError:
        return False
    if partes.fragment:
        return False
    return partes.scheme.lower() == "http" and host in _LOOPBACK


def redirect_uri_admitido(uri: str) -> bool:
    """¿Admite el DCR este ``redirect_uri``? Allowlist cerrada (ruling R11).

    Exactos: los callbacks de Claude (:data:`REDIRECTS_CLAUDE`) y los de
    ``MCP_REDIRECT_URIS_EXTRA``. Además, el loopback (:func:`_es_loopback`)
    para Claude Code y MCP Inspector, que escuchan en un puerto local.

    Un https cualquiera no basta: el registro es abierto y Google solo enseña el
    selector de cuenta de la app de TenderFlow, ya consentida. Un atacante que
    registrase ``https://evil.example/cb`` y le pasara a un admin un enlace a
    ``/authorize`` con su client_id y su PKCE recibiría el código del admin y lo
    canjearía (*confused deputy*, que las buenas prácticas de seguridad de MCP
    exigen impedir). Como el SDK exige en ``/authorize`` que el redirect coincida
    exactamente con uno registrado, limitar lo registrable cierra el ataque.
    """
    return uri in REDIRECTS_CLAUDE or uri in mcp_redirect_uris_extra() or _es_loopback(uri)


async def _en_hilo(f: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    """Llamada síncrona (BD, auditoría) fuera del bucle de eventos."""
    return await anyio.to_thread.run_sync(functools.partial(f, *args, **kwargs))


def _str_o_none(valor: object) -> str | None:
    return None if valor is None else str(valor)


# ---------------------------------------------------------------------------
# Proveedor
# ---------------------------------------------------------------------------


class ProveedorTenderFlow(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    """Proveedor OAuth del MCP: DCR, login con Google y tokens opacos rotativos."""

    def __init__(
        self,
        almacen: AlmacenOAuth,
        google: ClienteGoogle,
        *,
        usuarios: Callable[[str], dict[str, Any] | None] = get_active_user_by_email_ci,
        usuario_por_id: Callable[[int], dict[str, Any] | None] = get_user_by_id,
        acceso_permitido: Callable[[str], bool] = acceso_oauth_permitido,
        reloj: Callable[[], float] = time.time,
        auditar: Callable[[str, int | None, Mapping[str, object]], None] = auditar_oauth,
    ) -> None:
        self._almacen = almacen
        self._google = google
        self._usuarios = usuarios
        self._usuario_por_id = usuario_por_id
        self._acceso_permitido = acceso_permitido
        self._reloj = reloj
        self._auditar_sync = auditar
        #: user_id → (válido hasta, sigue siendo admin).
        self._cache_admin: dict[int, tuple[float, bool]] = {}

    # -- utilidades -------------------------------------------------------

    def _caduca(self, segundos: int) -> datetime:
        return datetime.fromtimestamp(self._reloj() + segundos, UTC)

    async def _auditar(
        self, accion: str, user_id: int | None, detalle: Mapping[str, object]
    ) -> None:
        await _en_hilo(self._auditar_sync, accion, user_id, detalle)

    def _admite(self, fila: Mapping[str, Any] | None) -> tuple[int | None, str]:
        """La regla de acceso sobre una fila de ``users``: ``(user_id, motivo)``."""
        if fila is None or fila.get("deactivated_at") is not None:
            return None, "sin_usuario_activo"
        if fila.get("is_admin") != 1:
            return None, "no_admin"
        if not self._acceso_permitido(str(fila.get("email") or "")):
            return None, "fuera_de_allowlist"
        return int(fila["id"]), ""

    def _resolver_admin(self, email: str) -> tuple[int | None, str]:
        """El ``usuario_activo_admin`` del login: ``(users.id, "")`` o ``(None, motivo)``.

        Síncrona: allowlist, cuenta activa (correo sin distinguir mayúsculas) e
        ``is_admin``. Devuelve el motivo para auditar la denegación.
        """
        if not self._acceso_permitido(email):
            return None, "fuera_de_allowlist"
        return self._admite(self._usuarios(email))

    async def _usuario_sigue_admin(self, user_id: int) -> bool:
        """Re-comprobación por petición (``is_admin``, ``deactivated_at``, allowlist), cacheada 60 s."""
        ahora = self._reloj()
        cacheado = self._cache_admin.get(user_id)
        if cacheado is not None and cacheado[0] > ahora:
            return cacheado[1]

        def _comprobar() -> bool:
            return self._admite(self._usuario_por_id(user_id))[0] is not None

        sigue = await _en_hilo(_comprobar)
        self._cache_admin[user_id] = (ahora + CACHE_ADMIN, sigue)
        return sigue

    def _nuevos(
        self,
        client_id: str,
        user_id: int,
        scopes_access: list[str],
        scopes_refresh: list[str],
        resource: str | None,
    ) -> tuple[str, str, list[TokenNuevo]]:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        datos = {"resource": resource}
        nuevos = [
            TokenNuevo(
                token=access,
                kind="access",
                client_id=client_id,
                user_id=user_id,
                scopes=scopes_access,
                expires_at=self._caduca(TTL_ACCESS),
                datos=datos,
            ),
            TokenNuevo(
                token=refresh,
                kind="refresh",
                client_id=client_id,
                user_id=user_id,
                scopes=scopes_refresh,
                expires_at=self._caduca(TTL_REFRESH),
                datos=datos,
            ),
        ]
        return access, refresh, nuevos

    async def _tratar_reutilizacion(
        self, token: str, kind: Literal["code", "refresh"], client_id: str
    ) -> None:
        """Un ``code``/``refresh`` ya consumido vuelve: se revoca su familia y se audita.

        El canje sin tokens nuevos de :meth:`AlmacenOAuth.consumir_y_emitir` es
        el que revoca, en su misma transacción; no se emite nada.
        """
        fila, reutilizado = await _en_hilo(self._almacen.consumir_y_emitir, token, kind, [])
        if fila is not None and reutilizado:
            await self._auditar_reutilizacion(kind, fila, client_id)

    async def _auditar_reutilizacion(
        self, kind: Literal["code", "refresh"], fila: Mapping[str, Any], client_id: str
    ) -> None:
        accion = "mcp.codigo_reutilizado" if kind == "code" else "mcp.refresh_reutilizado"
        await self._auditar(
            accion,
            fila["user_id"],
            {"client_id": client_id, "family_id": _str_o_none(fila["family_id"])},
        )

    @staticmethod
    def _respuesta(access: str, refresh: str, scopes: list[str]) -> OAuthToken:
        return OAuthToken(
            access_token=access,  # token_type: "Bearer" por defecto
            expires_in=TTL_ACCESS,
            refresh_token=refresh,
            scope=" ".join(scopes) or None,
        )

    # -- clientes ---------------------------------------------------------

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        fila = await _en_hilo(self._almacen.obtener_cliente, client_id)
        if fila is None:
            return None
        return OAuthClientInformationFull.model_validate(fila["datos"])

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        uris = [str(u) for u in client_info.redirect_uris or []]
        if not uris:
            raise RegistrationError("invalid_redirect_uri", "Hace falta al menos un redirect_uri.")
        for uri in uris:
            if not redirect_uri_admitido(uri):
                raise RegistrationError("invalid_redirect_uri", _FORMAS_ADMITIDAS)
        await _en_hilo(
            self._almacen.guardar_cliente,
            client_info.client_id,
            client_info.client_name,
            uris,
            client_info.model_dump(mode="json"),
        )

    # -- /authorize y vuelta de Google -----------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        state = generate_oauth_state()
        nonce = oauth_state_nonce(state)
        if nonce is None:  # pragma: no cover — generate_oauth_state siempre lo trae
            raise AuthorizeError("server_error", "state sin nonce")
        scopes = params.scopes
        if scopes is None:
            scopes = client.scope.split() if client.scope else []
        await _en_hilo(
            self._almacen.guardar_token,
            nonce,
            kind="pendiente",
            client_id=client.client_id,
            user_id=None,
            family_id=None,
            scopes=scopes,
            datos=params.model_dump(mode="json"),
            expires_at=self._caduca(TTL_PENDIENTE),
        )
        return self._google.url_autorizacion(state)

    async def completar_login(self, state: str, code: str | None, error: str | None) -> str:
        """Callback de Google: devuelve la URL del cliente a la que redirigir.

        Con el ``state`` inválido, caducado o ya usado no hay a quién volver:
        :class:`AuthorizeError` (``invalid_request``). Recuperada la petición,
        cualquier denegación vuelve al cliente con ``error=access_denied`` y su
        ``state`` original; el éxito, con un código de 60 s y un solo uso.
        """
        if not verify_oauth_state(state):
            raise AuthorizeError("invalid_request", "state inválido o caducado")
        nonce = oauth_state_nonce(state)
        if nonce is None:  # pragma: no cover — verify_oauth_state ya exige la forma
            raise AuthorizeError("invalid_request", "state inválido o caducado")
        pendiente, _ = await _en_hilo(self._almacen.consumir_token, nonce, "pendiente")
        if pendiente is None:
            raise AuthorizeError("invalid_request", "petición de autorización caducada o ya usada")

        params = AuthorizationParams.model_validate(pendiente["datos"])
        destino = str(params.redirect_uri)
        client_id = str(pendiente["client_id"])

        async def _denegar(motivo: str, email: str | None = None) -> str:
            detalle: dict[str, object] = {"motivo": motivo, "client_id": client_id}
            if email is not None:
                detalle["email"] = email
            await self._auditar("mcp.login_denegado", None, detalle)
            return construct_redirect_uri(destino, error="access_denied", state=params.state)

        if error is not None or not code:
            return await _denegar("google")
        identidad = await self._google.identidad(code, nonce)
        if identidad is None:
            return await _denegar("google")
        user_id, motivo = await _en_hilo(self._resolver_admin, identidad.email)
        if user_id is None:
            return await _denegar(motivo, identidad.email.strip().lower())

        codigo = secrets.token_urlsafe(32)
        await _en_hilo(
            self._almacen.guardar_token,
            codigo,
            kind="code",
            client_id=client_id,
            user_id=user_id,
            family_id=None,
            scopes=list(pendiente["scopes"]),
            datos={
                "code_challenge": params.code_challenge,
                "redirect_uri": destino,
                "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
                "resource": params.resource,
            },
            expires_at=self._caduca(TTL_CODIGO),
        )
        await self._auditar("mcp.login_ok", user_id, {"client_id": client_id})
        return construct_redirect_uri(destino, code=codigo, state=params.state)

    # -- código de autorización ------------------------------------------

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        fila = await _en_hilo(self._almacen.buscar_token, authorization_code, "code")
        if fila is None or fila["client_id"] != client.client_id:
            return None
        if fila["revoked_at"] is not None:
            # Código ya canjeado: el SDK respondería invalid_grant sin llegar al
            # canje, así que la reutilización se trata aquí (RFC 6749 §4.1.2:
            # se revoca lo emitido con él).
            await self._tratar_reutilizacion(authorization_code, "code", client.client_id)
            return None
        if fila["expires_at"].timestamp() <= self._reloj():
            return None
        datos: Mapping[str, Any] = fila["datos"] or {}
        return AuthorizationCode.model_validate(
            {
                "code": authorization_code,
                "scopes": fila["scopes"],
                "expires_at": fila["expires_at"].timestamp(),
                "client_id": fila["client_id"],
                "code_challenge": datos["code_challenge"],
                "redirect_uri": datos["redirect_uri"],
                "redirect_uri_provided_explicitly": datos["redirect_uri_provided_explicitly"],
                "resource": datos.get("resource"),
                "subject": str(fila["user_id"]),
            }
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        user_id = int(authorization_code.subject or 0)
        if not await self._usuario_sigue_admin(user_id):
            # Mismo texto que un código inválido: no se revela el motivo.
            raise TokenError("invalid_grant", "código de autorización inválido o ya usado")
        scopes = list(authorization_code.scopes)
        access, refresh, nuevos = self._nuevos(
            client.client_id, user_id, scopes, scopes, authorization_code.resource
        )
        fila, reutilizado = await _en_hilo(
            self._almacen.consumir_y_emitir, authorization_code.code, "code", nuevos
        )
        if fila is None or reutilizado:
            if fila is not None:
                # Otro canje del mismo código ganó; consumir_y_emitir ya revocó
                # lo que emitió.
                await self._auditar_reutilizacion("code", fila, client.client_id)
            raise TokenError("invalid_grant", "código de autorización inválido o ya usado")
        await self._auditar(
            "mcp.token_emitido",
            user_id,
            {"client_id": client.client_id, "family_id": _str_o_none(fila["family_id"])},
        )
        return self._respuesta(access, refresh, scopes)

    # -- refresh -----------------------------------------------------------

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        fila = await _en_hilo(self._almacen.buscar_token, refresh_token, "refresh")
        if fila is None or fila["client_id"] != client.client_id:
            return None
        if fila["revoked_at"] is not None:
            await self._tratar_reutilizacion(refresh_token, "refresh", client.client_id)
            return None
        if fila["expires_at"].timestamp() <= self._reloj():
            return None
        user_id = int(fila["user_id"])
        if not await self._usuario_sigue_admin(user_id):
            return None
        datos: Mapping[str, Any] = fila["datos"] or {}
        return RefreshToken(
            token=refresh_token,
            client_id=fila["client_id"],
            scopes=list(fila["scopes"]),
            expires_at=int(fila["expires_at"].timestamp()),
            resource=datos.get("resource"),
            subject=str(user_id),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        user_id = int(refresh_token.subject or 0)
        access, refresh, nuevos = self._nuevos(
            client.client_id,
            user_id,
            list(scopes),
            list(refresh_token.scopes),
            refresh_token.resource,
        )
        fila, reutilizado = await _en_hilo(
            self._almacen.consumir_y_emitir, refresh_token.token, "refresh", nuevos
        )
        if fila is None or reutilizado:
            if fila is not None:
                # Perdió la carrera con otro canje del mismo refresh: la familia
                # ya está revocada (lo hizo consumir_y_emitir).
                await self._auditar_reutilizacion("refresh", fila, client.client_id)
            raise TokenError("invalid_grant", "refresh token inválido o ya usado")
        await self._auditar(
            "mcp.token_rotado",
            user_id,
            {"client_id": client.client_id, "family_id": _str_o_none(fila["family_id"])},
        )
        return self._respuesta(access, refresh, list(scopes))

    # -- access y revocación ---------------------------------------------

    async def load_access_token(self, token: str) -> AccessToken | None:
        fila = await _en_hilo(self._almacen.obtener_token, token, "access")
        if fila is None:
            return None
        user_id = int(fila["user_id"])
        if not await self._usuario_sigue_admin(user_id):
            return None
        datos: Mapping[str, Any] = fila["datos"] or {}
        return AccessToken(
            token=token,
            client_id=fila["client_id"],
            scopes=list(fila["scopes"]),
            expires_at=int(fila["expires_at"].timestamp()),
            resource=datos.get("resource"),
            subject=str(user_id),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        kind: TipoToken = "refresh" if isinstance(token, RefreshToken) else "access"
        fila = await _en_hilo(self._almacen.buscar_token, token.token, kind)
        if fila is None:
            return
        familia = fila["family_id"]
        if familia is not None:
            await _en_hilo(self._almacen.revocar_familia, familia)
        else:
            await _en_hilo(self._almacen.revocar_token, token.token)
        await self._auditar(
            "mcp.token_revocado",
            fila["user_id"],
            {"client_id": token.client_id, "family_id": _str_o_none(familia)},
        )

    async def exchange_identity_assertion(
        self, client: OAuthClientInformationFull, params: IdentityAssertionParams
    ) -> OAuthToken:
        raise TokenError("unsupported_grant_type", "El grant jwt-bearer no está soportado.")
