"""Servidor MCP de punta a punta, en proceso: HTTP → OAuth → tool → Postgres → auditoría.

``starlette.testclient.TestClient`` como gestor de contexto (corre el lifespan,
que arranca el gestor de sesiones del SDK) y JSON-RPC a mano: con
``stateless_http=True`` y ``json_response=True`` cada POST es una petición
independiente con respuesta JSON, así que el diálogo es determinista.

El token de acceso se siembra con ``db.mcp_oauth`` (lo que habría emitido el
proveedor tras el login con Google) y el servidor lo valida con el proveedor
real contra Postgres, incluida la re-comprobación de ``is_admin``. ``consultar_sql``
lee con el rol efímero de ``rol_mcp``; las tools de dominio, por ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from starlette.testclient import TestClient

from db import mcp_oauth
from db.access_grants import grant_access
from db.connection import connect_read
from db.upsert import Licitacion, upsert_licitaciones
from db.users import create_user, set_admin
from mcp_server.servidor import crear_app

URL_PUBLICA = "http://localhost:8080"
CLIENTE = "cliente-e2e"
SEIS_TOOLS = {
    "describir_esquema",
    "describir_tabla",
    "consultar_sql",
    "buscar_licitaciones",
    "buscar_en_pliegos",
    "ficha_licitacion",
}


@pytest.fixture()
def usuarios(tmp_db: Any, rol_mcp: str) -> Iterator[dict[str, int]]:
    admin = create_user(email="ana@empresa.example", password_hash="x")  # pragma: allowlist secret
    set_admin(admin, True, granted_by="panel")
    ex_admin = create_user(
        email="luis@empresa.example", password_hash="x"
    )  # pragma: allowlist secret
    for email in ("ana@empresa.example", "luis@empresa.example"):
        grant_access("email", email, granted_by=None)
    mcp_oauth.guardar_cliente(CLIENTE, "E2E", ["http://localhost:3000/cb"], {"client_id": CLIENTE})
    # Mitad estática de la allowlist en «no», como en producción: decide `access_grants`.
    with patch("services.access_grants.oauth_email_allowed", return_value=False):
        yield {"admin": admin, "ex_admin": ex_admin}


def _sembrar_access(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    mcp_oauth.guardar_token(
        token,
        kind="access",
        client_id=CLIENTE,
        user_id=user_id,
        family_id=None,
        scopes=["tenderflow:leer"],
        datos={"resource": f"{URL_PUBLICA}/mcp"},
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    return token


@pytest.fixture()
def token_admin(usuarios: dict[str, int]) -> str:
    return _sembrar_access(usuarios["admin"])


@pytest.fixture()
def token_ex_admin(usuarios: dict[str, int]) -> str:
    """Token emitido cuando era admin; después se le quitó el permiso."""
    token = _sembrar_access(usuarios["ex_admin"])
    set_admin(usuarios["ex_admin"], False)
    return token


@pytest.fixture()
def app_cliente(usuarios: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MCP_PUBLIC_URL", URL_PUBLICA)
    monkeypatch.setenv("MCP_GOOGLE_REDIRECT_URI", f"{URL_PUBLICA}/oauth/google/callback")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "db")
    from services.rate_limiting import reset_rate_limiter

    reset_rate_limiter()
    with TestClient(crear_app(), base_url=URL_PUBLICA) as cliente:
        yield cliente
    reset_rate_limiter()


def _cabeceras(token: str | None) -> dict[str, str]:
    cabeceras = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": LATEST_HANDSHAKE_VERSION,
    }
    if token is not None:
        cabeceras["Authorization"] = f"Bearer {token}"
    return cabeceras


def _initialize() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_HANDSHAKE_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "e2e", "version": "1"},
        },
    }


def _rpc(cliente: TestClient, token: str, metodo: str, params: dict[str, Any]) -> dict[str, Any]:
    r = cliente.post(
        "/mcp",
        headers=_cabeceras(token),
        json={"jsonrpc": "2.0", "id": 2, "method": metodo, "params": params},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    cuerpo: dict[str, Any] = r.json()
    assert "error" not in cuerpo, cuerpo
    resultado: dict[str, Any] = cuerpo["result"]
    return resultado


def _handshake(cliente: TestClient, token: str) -> dict[str, Any]:
    r = cliente.post("/mcp", headers=_cabeceras(token), json=_initialize())
    assert r.status_code == 200, r.text
    inicial: dict[str, Any] = r.json()["result"]
    r = cliente.post(
        "/mcp",
        headers=_cabeceras(token),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert r.status_code == 202
    return inicial


def _tools_list(cliente: TestClient, token: str) -> list[dict[str, Any]]:
    _handshake(cliente, token)
    tools: list[dict[str, Any]] = _rpc(cliente, token, "tools/list", {})["tools"]
    return tools


def _llamar(cliente: TestClient, token: str, nombre: str, args: dict[str, Any]) -> dict[str, Any]:
    _handshake(cliente, token)
    return _rpc(cliente, token, "tools/call", {"name": nombre, "arguments": args})


def _auditoria(accion: str) -> list[tuple[int | None, dict[str, Any]]]:
    with connect_read() as c:
        filas = c.execute(
            "SELECT user_id, detail FROM audit_log WHERE action = %s ORDER BY id", (accion,)
        ).fetchall()
    return [(f[0], json.loads(f[1])) for f in filas]


def test_sin_token_401_con_resource_metadata(app_cliente: TestClient) -> None:
    r = app_cliente.post("/mcp", headers=_cabeceras(None), json=_initialize())
    assert r.status_code == 401
    cabecera = r.headers["www-authenticate"]
    assert "resource_metadata" in cabecera
    assert f"{URL_PUBLICA}/.well-known/oauth-protected-resource/mcp" in cabecera


def test_metadatos_oauth_publicados(app_cliente: TestClient) -> None:
    servidor = app_cliente.get("/.well-known/oauth-authorization-server").json()
    assert servidor["registration_endpoint"] == f"{URL_PUBLICA}/register"
    assert servidor["revocation_endpoint"] == f"{URL_PUBLICA}/revoke"
    assert servidor["scopes_supported"] == ["tenderflow:leer"]
    recurso = app_cliente.get("/.well-known/oauth-protected-resource/mcp")
    assert recurso.status_code == 200
    assert recurso.json()["resource"] == f"{URL_PUBLICA}/mcp"
    assert recurso.json()["authorization_servers"] == [URL_PUBLICA]


def test_initialize_trae_instrucciones_y_glosario(
    app_cliente: TestClient, token_admin: str
) -> None:
    inicial = _handshake(app_cliente, token_admin)
    assert inicial["serverInfo"]["name"] == "tenderflow"
    assert "describir_esquema" in inicial["instructions"]
    assert "importe" in inicial["instructions"]  # el glosario va detrás


def test_lista_las_seis_tools_de_solo_lectura(app_cliente: TestClient, token_admin: str) -> None:
    tools = _tools_list(app_cliente, token_admin)
    assert {t["name"] for t in tools} == SEIS_TOOLS
    for t in tools:
        assert t["annotations"]["readOnlyHint"] is True
        assert t["annotations"]["destructiveHint"] is False
        assert t["annotations"]["idempotentHint"] is True
        assert t["annotations"]["openWorldHint"] is False
        assert t["description"]
        for nombre, propiedad in t["inputSchema"].get("properties", {}).items():
            assert propiedad.get("description"), (t["name"], nombre)
    buscar = next(t for t in tools if t["name"] == "buscar_licitaciones")
    limite = buscar["inputSchema"]["properties"]["limite"]
    assert (limite["default"], limite["minimum"], limite["maximum"]) == (20, 1, 50)
    assert buscar["inputSchema"]["required"] == ["texto"]


def test_consultar_sql_devuelve_filas_y_audita(
    app_cliente: TestClient, token_admin: str, usuarios: dict[str, int]
) -> None:
    upsert_licitaciones([Licitacion(id_externo="EXP-E2E-1", titulo="Soporte SAP")])
    sql = "SELECT id_externo, titulo FROM licitaciones ORDER BY id_externo"

    resultado = _llamar(app_cliente, token_admin, "consultar_sql", {"sql": sql})

    assert resultado["isError"] is False
    datos = resultado["structuredContent"]
    assert datos["columnas"] == ["id_externo", "titulo"]
    assert datos["filas"] == [["EXP-E2E-1", "Soporte SAP"]]
    assert json.loads(resultado["content"][0]["text"]) == datos
    ((user_id, detalle),) = _auditoria("mcp.consultar_sql")
    assert user_id == usuarios["admin"]
    assert detalle["args"] == {"sql": sql}
    assert detalle["n_filas"] == 1 and detalle["error"] is None


def test_consultar_sql_de_escritura_es_error_de_tool(
    app_cliente: TestClient, token_admin: str
) -> None:
    resultado = _llamar(
        app_cliente, token_admin, "consultar_sql", {"sql": "DELETE FROM licitaciones"}
    )
    assert resultado["isError"] is True
    texto = resultado["content"][0]["text"]
    assert "SQLSTATE" in texto and "Traceback" not in texto
    ((_, detalle),) = _auditoria("mcp.consultar_sql")
    assert detalle["error"] and detalle["n_filas"] is None


def test_argumentos_fuera_de_esquema_son_error_compacto(
    app_cliente: TestClient, token_admin: str
) -> None:
    resultado = _llamar(
        app_cliente, token_admin, "buscar_licitaciones", {"texto": "sap", "limite": 500}
    )
    assert resultado["isError"] is True
    texto = resultado["content"][0]["text"]
    assert "limite" in texto and "errors.pydantic.dev" not in texto
    ((_, detalle),) = _auditoria("mcp.buscar_licitaciones")
    assert "limite" in detalle["error"]


def test_ficha_inexistente_trae_pista(app_cliente: TestClient, token_admin: str) -> None:
    resultado = _llamar(app_cliente, token_admin, "ficha_licitacion", {"id_externo": "NO-EXISTE"})
    assert resultado["isError"] is True
    # Exactamente "{mensaje}\nPista: {pista}", sin el prefijo "Error executing tool" del SDK.
    assert resultado["content"][0]["text"] == (
        "No existe la licitación 'NO-EXISTE'.\nPista: búscala con buscar_licitaciones"
    )


def test_token_de_no_admin_rechazado(app_cliente: TestClient, token_ex_admin: str) -> None:
    r = app_cliente.post("/mcp", headers=_cabeceras(token_ex_admin), json=_initialize())
    assert r.status_code == 401


def test_token_desconocido_rechazado(app_cliente: TestClient) -> None:
    r = app_cliente.post("/mcp", headers=_cabeceras("no-es-un-token"), json=_initialize())
    assert r.status_code == 401


def test_healthz(app_cliente: TestClient) -> None:
    assert app_cliente.get("/healthz").json() == {"ok": True}


def test_callback_de_google_con_state_invalido_es_400(app_cliente: TestClient) -> None:
    r = app_cliente.get("/oauth/google/callback", params={"state": "falso", "code": "c"})
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("text/html")
    r = app_cliente.get("/oauth/google/callback")
    assert r.status_code == 400


def test_host_ajeno_rechazado(app_cliente: TestClient, token_admin: str) -> None:
    """Protección DNS rebinding: solo el host de ``MCP_PUBLIC_URL`` (y loopback)."""
    cabeceras = {**_cabeceras(token_admin), "Host": "evil.example"}
    r = app_cliente.post("/mcp", headers=cabeceras, json=_initialize())
    assert r.status_code == 421
