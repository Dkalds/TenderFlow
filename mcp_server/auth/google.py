"""Login con Google para el servidor de autorización del MCP.

El MCP delega la identidad en el cliente OAuth de Google que ya usa el producto,
con un redirect URI propio (``MCP_GOOGLE_REDIRECT_URI``). Este módulo hace las
dos mitades del salto a Google: la URL a la que se manda al navegador y, de
vuelta, el canje del código por un ``id_token`` verificado.

El ``state`` hacia Google lo genera el proveedor (``shared.auth_core``, firmado
con ``SIGNING_KEY``); su nonce viaja también como ``nonce`` OIDC y se exige en
el ``id_token``, de modo que un código de Google emitido para otro flujo no
sirve para completar este.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import anyio.to_thread
import httpx

from config import settings
from config.settings import mcp_google_redirect_uri
from observability.logging import get_logger
from shared.auth_core import oauth_email_parts, oauth_state_nonce, verify_google_id_token

__all__ = ["ClienteGoogle", "ClienteGoogleReal", "IdentidadGoogle"]

log = get_logger(__name__)

_URL_AUTORIZACION = "https://accounts.google.com/o/oauth2/v2/auth"
# No es una contraseña: es la URL pública del endpoint de token de Google
# (ruff S105 y bandit B105 miran el nombre, no el valor).
_URL_TOKEN = "https://oauth2.googleapis.com/token"  # noqa: S105  # nosec B105
_SCOPE = "openid email"


@dataclass(frozen=True)
class IdentidadGoogle:
    """Cuenta de Google verificada: ``email`` tal como lo manda Google y su ``sub``."""

    email: str
    sub: str


class ClienteGoogle(Protocol):
    """Lo que el proveedor necesita de Google (``GoogleFalso`` en los tests)."""

    def url_autorizacion(self, state: str) -> str:
        """URL de Google a la que se redirige al navegador para este ``state``."""
        ...

    async def identidad(self, code: str, nonce: str) -> IdentidadGoogle | None:
        """Canjea ``code`` y devuelve la identidad, o ``None`` si algo no cuadra.

        ``nonce`` es el del ``state`` del flujo: el ``id_token`` tiene que traerlo.
        """
        ...


#: Firma de ``shared.auth_core.verify_google_id_token`` (inyectable en tests).
VerificadorIdToken = Callable[..., dict[str, Any] | None]


class ClienteGoogleReal:
    """Google de verdad: ``httpx`` para el canje y ``verify_google_id_token`` para la firma.

    Las credenciales y el redirect URI se leen en cada llamada (``settings`` y
    ``mcp_google_redirect_uri()``), para que el proceso arranque aunque falten:
    la validación de la configuración es del arranque del MCP.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        verificar: VerificadorIdToken = verify_google_id_token,
    ) -> None:
        self._transport = transport
        self._verificar = verificar

    def url_autorizacion(self, state: str) -> str:
        nonce = oauth_state_nonce(state)
        if nonce is None:
            raise ValueError("state sin nonce válido")
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": mcp_google_redirect_uri(),
            "response_type": "code",
            "scope": _SCOPE,
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
            "access_type": "online",
        }
        return f"{_URL_AUTORIZACION}?{urllib.parse.urlencode(params)}"

    async def identidad(self, code: str, nonce: str) -> IdentidadGoogle | None:
        client_id = settings.GOOGLE_CLIENT_ID
        try:
            async with httpx.AsyncClient(timeout=10.0, transport=self._transport) as http:
                respuesta = await http.post(
                    _URL_TOKEN,
                    data={
                        "code": code,
                        "client_id": client_id,
                        "client_secret": settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
                        "redirect_uri": mcp_google_redirect_uri(),
                        "grant_type": "authorization_code",
                    },
                )
        except httpx.HTTPError as exc:
            log.warning("mcp_google_canje_sin_red", error_type=type(exc).__name__)
            return None
        if respuesta.status_code != 200:
            log.warning("mcp_google_canje_rechazado", status=respuesta.status_code)
            return None
        try:
            cuerpo = respuesta.json()
        except ValueError:
            cuerpo = None
        id_token = cuerpo.get("id_token") if isinstance(cuerpo, dict) else None
        if not isinstance(id_token, str) or not id_token:
            log.warning("mcp_google_canje_sin_id_token")
            return None

        verificar = self._verificar
        # Síncrona (descarga las claves de Google con `httpx.get`): a un hilo.
        claims = await anyio.to_thread.run_sync(
            lambda: verificar(id_token, audience=client_id, expected_nonce=nonce)
        )
        if claims is None:
            return None
        # `verify_google_id_token` ya lo exige; se repite aquí porque es lo que
        # hace que el correo identifique a la persona, y el verificador se inyecta.
        if claims.get("email_verified") not in (True, "true", "True"):
            log.warning("mcp_google_email_sin_verificar")
            return None
        email = str(claims.get("email") or "").strip()
        sub = str(claims.get("sub") or "")
        if oauth_email_parts(email) is None or not sub:
            log.warning("mcp_google_identidad_incompleta")
            return None
        return IdentidadGoogle(email=email, sub=sub)
