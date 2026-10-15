"""El servidor MCP: ``MCPServer`` del SDK con OAuth, las seis tools y dos rutas propias.

Transporte Streamable HTTP **sin estado** y con respuestas JSON
(``stateless_http=True``, ``json_response=True``): cada ``POST /mcp`` es una
petición independiente, sin ``Mcp-Session-Id`` que guardar, así que el servicio
escala y se reinicia sin perder nada. El SDK monta además:

- ``/authorize``, ``/token``, ``/register`` y ``/revoke`` sobre
  :class:`~mcp_server.auth.proveedor.ProveedorTenderFlow`, y los metadatos
  ``/.well-known/oauth-authorization-server`` (RFC 8414) y
  ``/.well-known/oauth-protected-resource/mcp`` (RFC 9728).
- El middleware Bearer: ``/mcp`` sin token válido responde ``401`` con
  ``WWW-Authenticate: Bearer … resource_metadata="…"``, que es como un cliente
  MCP descubre el servidor de autorización.

Las rutas propias (``custom_route``, sin autenticación) son ``GET /healthz``
para Render y ``GET /oauth/google/callback``, la vuelta del login de Google.

Protección DNS rebinding del SDK: con ``host="0.0.0.0"`` viene apagada, así que
se configura explícitamente con el host de ``MCP_PUBLIC_URL`` (el ``Host`` que
manda Render) y el loopback para desarrollo.
"""

from __future__ import annotations

import html
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

from mcp.server.auth.provider import AuthorizeError
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, InputRequiredResult, ToolAnnotations
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from config import settings
from config.settings import mcp_database_url, mcp_google_redirect_uri, mcp_public_url
from db.consulta_libre import JSONValue, cerrar_pool_mcp
from mcp_server.auth.google import ClienteGoogleReal
from mcp_server.auth.proveedor import AlmacenOAuthPostgres, ProveedorTenderFlow
from mcp_server.envoltura import auditar_rechazo, herramienta, resumir_validacion
from mcp_server.tools.consulta import consultar_sql
from mcp_server.tools.dominio import buscar_en_pliegos, buscar_licitaciones, ficha_licitacion
from mcp_server.tools.esquema import describir_esquema, describir_tabla, glosario

__all__ = ["SCOPE", "crear_app", "crear_servidor", "validar_configuracion"]

#: El único scope del servidor: todo es lectura.
SCOPE = "tenderflow:leer"
#: ``MCP_PUBLIC_URL`` en desarrollo si no está configurada (en prod aborta el arranque).
_URL_LOCAL = "http://localhost:8080"
#: Orígenes de navegador admitidos además del propio y el loopback. Los
#: conectores de claude.ai y ChatGPT llaman desde sus servidores (sin
#: ``Origin``); estos cubren el caso de que lo hagan desde el navegador.
_ORIGENES_CLIENTES = ("https://claude.ai", "https://claude.com", "https://chatgpt.com")

_INSTRUCCIONES = """\
Servidor de solo lectura sobre la base de datos de licitaciones públicas de TenderFlow.
Empieza por describir_esquema (tablas y glosario) y describir_tabla; agrega, cuenta y cruza con consultar_sql (SELECT de PostgreSQL, 500 filas como máximo).
Para expedientes concretos usa buscar_licitaciones y ficha_licitacion, y buscar_en_pliegos para el texto de los pliegos.
"""

_SOLO_LECTURA = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

#: ``(nombre, título, función)`` de las seis tools, en el orden en que se listan.
_TOOLS: tuple[tuple[str, str, Callable[..., Mapping[str, JSONValue]]], ...] = (
    ("describir_esquema", "Describir el esquema", describir_esquema),
    ("describir_tabla", "Describir una tabla", describir_tabla),
    ("consultar_sql", "Consultar con SQL", consultar_sql),
    ("buscar_licitaciones", "Buscar licitaciones", buscar_licitaciones),
    ("buscar_en_pliegos", "Buscar en los pliegos", buscar_en_pliegos),
    ("ficha_licitacion", "Ficha de una licitación", ficha_licitacion),
)


def validar_configuracion() -> list[str]:
    """Variables obligatorias del MCP que faltan (vacías), en orden fijo."""
    valores = {
        "MCP_DATABASE_URL": mcp_database_url(),
        "MCP_PUBLIC_URL": mcp_public_url(),
        "MCP_GOOGLE_REDIRECT_URI": mcp_google_redirect_uri(),
        "DATABASE_URL": settings.DATABASE_URL.get_secret_value(),
        "GOOGLE_CLIENT_ID": settings.GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": settings.GOOGLE_CLIENT_SECRET.get_secret_value(),
        "SIGNING_KEY": settings.SIGNING_KEY.get_secret_value(),
    }
    return [nombre for nombre, valor in valores.items() if not valor.strip()]


def _url_publica() -> str:
    return mcp_public_url() or _URL_LOCAL


class _ServidorTenderFlow(MCPServer[None]):
    """``MCPServer`` que compacta y audita los argumentos que el SDK rechaza.

    El SDK valida los argumentos contra el esquema de la firma **antes** de
    llamar a la tool, así que esas llamadas no pasan por :func:`herramienta`.
    Sin esto, el LLM recibiría el volcado entero de pydantic (con enlaces a su
    documentación) y la llamada no quedaría auditada.
    """

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[None, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        try:
            return await super().call_tool(name, arguments, context)
        except UnexpectedToolError:
            raise
        except ToolError as exc:
            causa = exc.__cause__
            if not isinstance(causa, ValidationError):
                raise
            mensaje = resumir_validacion(causa)
            await auditar_rechazo(name, arguments, mensaje)
            # La causa se conserva: el SDK registra (solo) los nombres de los campos.
            raise ToolError(mensaje) from causa


@asynccontextmanager
async def _ciclo_de_vida(_: MCPServer[None]) -> AsyncIterator[None]:
    """Cierra el pool del rol MCP al apagar (el lifespan lo entra una vez el gestor HTTP)."""
    try:
        yield
    finally:
        cerrar_pool_mcp()


def _pagina_error(descripcion: str) -> HTMLResponse:
    cuerpo = (
        "<!doctype html><html lang='es'><meta charset='utf-8'>"
        "<title>TenderFlow MCP</title>"
        "<h1>No se pudo completar el inicio de sesión</h1>"
        f"<p>{html.escape(descripcion)}</p>"
        "<p>Vuelve a conectar el servidor desde tu cliente MCP.</p></html>"
    )
    return HTMLResponse(cuerpo, status_code=400, headers={"Cache-Control": "no-store"})


def _ajustes_auth(url: str) -> AuthSettings:
    # `model_validate` con la URL en texto, no `AnyHttpUrl(url)`: así se aplica
    # `url_preserve_empty_path` de `AuthSettings` y el issuer no gana una «/»
    # final (RFC 8414 compara el issuer como cadena exacta).
    return AuthSettings.model_validate(
        {
            "issuer_url": url,
            "resource_server_url": f"{url}/mcp",
            "client_registration_options": ClientRegistrationOptions(
                enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
            ),
            "revocation_options": RevocationOptions(enabled=True),
            "required_scopes": [SCOPE],
            # El proveedor no ata el access token a un `resource`: es el único
            # recurso que sirve este servidor de autorización.
            "validate_token_resource": False,
        }
    )


def crear_servidor(proveedor: ProveedorTenderFlow | None = None) -> MCPServer[None]:
    """El ``MCPServer`` con OAuth, las seis tools y las rutas ``/healthz`` y del callback."""
    if proveedor is None:
        proveedor = ProveedorTenderFlow(AlmacenOAuthPostgres(), ClienteGoogleReal())
    url = _url_publica()
    servidor = _ServidorTenderFlow(
        "tenderflow",
        title="TenderFlow",
        instructions=f"{_INSTRUCCIONES}\n{glosario()}",
        auth_server_provider=proveedor,
        auth=_ajustes_auth(url),
        lifespan=_ciclo_de_vida,
    )
    for nombre, titulo, fn in _TOOLS:
        servidor.tool(name=nombre, title=titulo, annotations=_SOLO_LECTURA)(herramienta(nombre, fn))

    async def healthz(_: Request) -> Response:
        return JSONResponse({"ok": True})

    async def callback_google(request: Request) -> Response:
        q = request.query_params
        state = q.get("state")
        if not state:
            return _pagina_error("Falta el parámetro state.")
        try:
            destino = await proveedor.completar_login(state, q.get("code"), q.get("error"))
        except AuthorizeError as exc:
            return _pagina_error(exc.error_description or "Petición de autorización no válida.")
        # La URL lleva el código de autorización: que nadie la guarde.
        return RedirectResponse(destino, status_code=302, headers={"Cache-Control": "no-store"})

    # `custom_route` en forma de llamada: como decorador mypy lo ve sin tipos.
    servidor.custom_route("/healthz", methods=["GET"])(healthz)
    servidor.custom_route("/oauth/google/callback", methods=["GET"])(callback_google)
    return servidor


def _seguridad_transporte(url: str) -> TransportSecuritySettings:
    partes = urlsplit(url)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[partes.netloc, "localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*"],
        allowed_origins=[
            f"{partes.scheme}://{partes.netloc}",
            *_ORIGENES_CLIENTES,
            "http://localhost:*",
            "http://127.0.0.1:*",
        ],
    )


def crear_app() -> Starlette:
    """La app ASGI: ``/mcp`` (Streamable HTTP sin estado, JSON) más OAuth y las rutas propias."""
    return crear_servidor().streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        # Escucha en todas las interfaces (contenedor de Render); la validación de
        # `Host` la hace `transport_security`, no la interfaz.
        host="0.0.0.0",  # noqa: S104  # nosec B104
        transport_security=_seguridad_transporte(_url_publica()),
    )
