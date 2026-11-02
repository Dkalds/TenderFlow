"""IP del cliente en el MCP: de ``X-Forwarded-For`` al ``ContextVar`` que lee el proveedor."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import Scope

from mcp_server.auth.proveedor import ip_cliente
from mcp_server.servidor import _ip_del_cliente, _IpDelCliente


def _scope(par: str | None, *forwarded: str) -> Scope:
    return {
        "type": "http",
        "headers": [(b"x-forwarded-for", f.encode("latin-1")) for f in forwarded],
        "client": None if par is None else (par, 12345),
    }


@pytest.mark.parametrize(
    ("scope", "esperada"),
    [
        # Render añade la IP del cliente al final; el par TCP es un nodo interno.
        (_scope("10.19.4.7", "93.184.216.34"), "93.184.216.34"),
        # Lo que escribe quien llama va a la izquierda: gana el salto de la plataforma.
        (_scope("10.19.4.7", "1.2.3.4, 93.184.216.34"), "93.184.216.34"),
        (_scope("10.19.4.7", "1.2.3.4", "93.184.216.34"), "93.184.216.34"),
        # Un salto interno al final (otro proxy de la plataforma) se salta.
        (_scope("10.19.4.7", "93.184.216.34, 10.0.0.2"), "93.184.216.34"),
        # Sin cabecera, el par TCP si es público.
        (_scope("93.184.216.34"), "93.184.216.34"),
        # Basura en la cabecera no rompe nada.
        (_scope("10.1.1.1", "no-es-una-ip, 93.184.216.34, "), "93.184.216.34"),
        # IPv6: por /64.
        (_scope("10.1.1.1", "2a00:1450:4001:81b:1:2:3:4"), "2a00:1450:4001:81b::/64"),
        (_scope("10.1.1.1", "2a00:1450:4001:81b:ffff::1"), "2a00:1450:4001:81b::/64"),
        # Desarrollo local: nada público, no hay límite por IP.
        (_scope("127.0.0.1"), None),
        (_scope("testclient"), None),
        (_scope(None), None),
        (_scope("10.1.1.1", "192.168.0.4, 169.254.1.1"), None),
    ],
)
def test_ip_del_cliente(scope: Scope, esperada: str | None) -> None:
    assert _ip_del_cliente(scope) == esperada


def test_el_middleware_deja_la_ip_visible_en_el_handler_y_la_restablece() -> None:
    vistas: list[str | None] = []

    async def handler(_: Request) -> JSONResponse:
        vistas.append(ip_cliente.get())
        return JSONResponse({})

    app = Starlette(routes=[Route("/", handler)])
    app.add_middleware(_IpDelCliente)
    cliente: Any = TestClient(app)
    cliente.get("/", headers={"X-Forwarded-For": "93.184.216.34"})
    cliente.get("/")  # el par de TestClient no es una IP: sin límite por IP
    assert vistas == ["93.184.216.34", None]
    assert ip_cliente.get() is None


# ── Cookie que liga el login de Google al navegador de /authorize ──────────


def _app_con_cookie_de_login(
    segura: bool, valor: str | None
) -> tuple[Starlette, list[dict[str, str] | None]]:
    from starlette.responses import RedirectResponse

    from mcp_server.auth.proveedor import ligadura_navegador
    from mcp_server.servidor import _CookieDeLogin

    cajones: list[dict[str, str] | None] = []

    async def authorize(_: Request) -> RedirectResponse:
        cajon = ligadura_navegador.get()
        cajones.append(cajon)
        if cajon is not None and valor is not None:
            cajon["valor"] = valor
        return RedirectResponse("https://google.test/auth", status_code=302)

    async def otra(_: Request) -> JSONResponse:
        cajones.append(ligadura_navegador.get())
        return JSONResponse({})

    app = Starlette(routes=[Route("/authorize", authorize), Route("/otra", otra)])
    app.add_middleware(_CookieDeLogin, segura=segura)
    return app, cajones


def test_authorize_manda_la_cookie_de_ligadura_con_la_redireccion() -> None:
    app, cajones = _app_con_cookie_de_login(segura=True, valor="abc123")
    r = TestClient(app).get("/authorize", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "https://google.test/auth"
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("mcp_login=abc123;")
    # Solo viaja al callback de Google, no a JS y no entre sitios salvo en navegación.
    for atributo in ("Path=/oauth/google/callback", "HttpOnly", "SameSite=Lax", "Secure"):
        assert atributo in cookie
    assert "Max-Age=600" in cookie
    assert cajones and ligadura_navegador_vacio()


def ligadura_navegador_vacio() -> bool:
    from mcp_server.auth.proveedor import ligadura_navegador

    return ligadura_navegador.get() is None


def test_en_desarrollo_la_cookie_no_lleva_secure() -> None:
    app, _ = _app_con_cookie_de_login(segura=False, valor="abc123")
    cookie = TestClient(app).get("/authorize", follow_redirects=False).headers["set-cookie"]
    assert "Secure" not in cookie


def test_sin_valor_del_proveedor_o_en_otra_ruta_no_hay_cookie() -> None:
    """Un ``/authorize`` rechazado (cliente desconocido...) no llega a fijar valor alguno."""
    app, cajones = _app_con_cookie_de_login(segura=True, valor=None)
    cliente = TestClient(app)
    assert "set-cookie" not in cliente.get("/authorize", follow_redirects=False).headers
    assert "set-cookie" not in cliente.get("/otra").headers
    assert cajones[-1] is None  # fuera de /authorize no se abre cajón
