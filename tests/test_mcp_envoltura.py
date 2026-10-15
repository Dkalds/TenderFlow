"""Envoltura de las tools del MCP (``mcp_server/envoltura.py``) y arranque, sin Postgres.

Qué se fija
-----------
- Cada llamada se audita **siempre** (también si falla o la corta el límite)
  con ``action = "mcp.<tool>"``, el SQL completo, ``n_filas``, la duración y el
  error, bajo la clave ``user:<id>`` de ``auditar_oauth``.
- Rate limit por usuario: ``mcp:min:<id>`` (60/60 s) y ``mcp:dia:<id>``
  (1 000/86 400 s); superarlo es un error de tool con el tiempo de espera.
- Los errores llegan al LLM como ``ToolError`` legibles: ``ErrorHerramienta`` y
  ``ErrorConsulta`` con su pista, ``ValidationError`` como lista compacta de
  campos, y cualquier otra cosa como un mensaje genérico sin traza.
- La firma de la tool original se conserva (el SDK construye el esquema de
  entrada con ella) y la salida va en ``structuredContent`` y como JSON compacto.
- ``validar_configuracion`` enumera lo que falta; ``__main__`` aborta en prod.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Iterator
from typing import Any

import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from db.consulta_libre import ErrorConsulta, ResultadoConsulta
from mcp_server import envoltura
from mcp_server.auth import proveedor
from mcp_server.tools import ErrorHerramienta, consulta
from mcp_server.tools.dominio import buscar_licitaciones

pytestmark = pytest.mark.anyio


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


class LimiterFalso:
    def __init__(self, deniega: set[str] | None = None) -> None:
        self.deniega = deniega or set()
        self.llamadas: list[tuple[str, int, float]] = []

    def check(self, key: str, *, max_calls: int = 120, window_seconds: float = 60.0) -> bool:
        self.llamadas.append((key, max_calls, window_seconds))
        return key.split(":")[1] not in self.deniega


@pytest.fixture()
def limiter(monkeypatch: pytest.MonkeyPatch) -> LimiterFalso:
    falso = LimiterFalso()
    monkeypatch.setattr(envoltura, "get_rate_limiter", lambda: falso)
    return falso


@pytest.fixture()
def auditoria(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
    """``log_action`` parcheado donde lo llama ``auditar_oauth`` (la única llamada del MCP)."""
    llamadas: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    monkeypatch.setattr(proveedor, "log_action", lambda *a, **k: llamadas.append((a, k)))
    return llamadas


@pytest.fixture()
def token(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    acceso = AccessToken(
        token="t", client_id="c", scopes=["tenderflow:leer"], expires_at=None, subject="7"
    )
    monkeypatch.setattr(envoltura, "get_access_token", lambda: acceso)
    yield


@pytest.fixture()
def servidor(monkeypatch: pytest.MonkeyPatch) -> Any:
    """El servidor real con un proveedor que no se usa: se llama a ``call_tool`` sin HTTP."""
    from mcp_server.auth.proveedor import ProveedorTenderFlow
    from mcp_server.servidor import crear_servidor

    monkeypatch.setenv("MCP_PUBLIC_URL", "http://localhost:8080")
    falso = ProveedorTenderFlow(almacen=None, google=None)  # type: ignore[arg-type]  # no se usan
    return crear_servidor(falso)


def _detalle(auditoria: list[tuple[tuple[Any, ...], dict[str, Any]]]) -> dict[str, Any]:
    (args, kwargs), *_ = auditoria
    assert args[0] == "user:7" and args[1] == "mcp" and kwargs == {"user_id": 7}
    detalle: dict[str, Any] = json.loads(args[3])
    return detalle


def _texto(resultado: CallToolResult) -> str:
    (bloque,) = resultado.content
    assert isinstance(bloque, TextContent)
    return bloque.text


@pytest.mark.usefixtures("token")
async def test_audita_exito_con_sql_y_filas(
    monkeypatch: pytest.MonkeyPatch, limiter: LimiterFalso, auditoria: list[Any], servidor: Any
) -> None:
    resultado_db = ResultadoConsulta(
        columnas=["uno"], filas=[[1], [2]], n_filas=2, truncado=False, duracion_ms=3
    )
    monkeypatch.setattr(consulta, "ejecutar_select", lambda sql: resultado_db)

    resultado = await servidor.call_tool("consultar_sql", {"sql": "SELECT 1 AS uno -- ñ"})

    assert resultado.structured_content == resultado_db.como_dict()
    # JSON compacto (sin sangría) y legible (sin escapar acentos).
    assert _texto(resultado) == json.dumps(
        resultado_db.como_dict(), ensure_ascii=False, separators=(",", ":")
    )
    (args, _), *resto = auditoria
    assert not resto and args[2] == "mcp.consultar_sql"
    detalle = _detalle(auditoria)
    assert detalle["args"] == {"sql": "SELECT 1 AS uno -- ñ"}
    assert detalle["n_filas"] == 2 and detalle["error"] is None
    assert isinstance(detalle["duracion_ms"], int)
    assert limiter.llamadas == [("mcp:min:7", 60, 60), ("mcp:dia:7", 1000, 86400)]


@pytest.mark.usefixtures("token", "limiter")
async def test_audita_tambien_el_error(
    monkeypatch: pytest.MonkeyPatch, auditoria: list[Any], servidor: Any
) -> None:
    def falla(sql: str) -> ResultadoConsulta:
        raise ErrorConsulta("42P01", "no existe la relación «nada»", "usa describir_esquema")

    monkeypatch.setattr(consulta, "ejecutar_select", falla)

    with pytest.raises(ToolError) as exc:
        await servidor.call_tool("consultar_sql", {"sql": "SELECT * FROM nada"})

    # Exactamente "{mensaje}\nPista: {pista}": sin el prefijo "Error executing tool …" del SDK.
    assert str(exc.value) == (
        "no existe la relación «nada» (SQLSTATE 42P01)\nPista: usa describir_esquema"
    )
    detalle = _detalle(auditoria)
    assert detalle["args"] == {"sql": "SELECT * FROM nada"}
    assert detalle["n_filas"] is None
    assert "no existe la relación" in detalle["error"]


@pytest.mark.usefixtures("token")
async def test_rate_limit_por_minuto(
    monkeypatch: pytest.MonkeyPatch, limiter: LimiterFalso, auditoria: list[Any], servidor: Any
) -> None:
    limiter.deniega = {"min"}
    llamadas: list[str] = []
    monkeypatch.setattr(consulta, "ejecutar_select", llamadas.append)

    with pytest.raises(ToolError) as exc:
        await servidor.call_tool("consultar_sql", {"sql": "SELECT 1"})
    assert str(exc.value) == "Límite de uso alcanzado\nPista: espera 60 s"
    assert llamadas == []
    (args, _), *resto = auditoria
    assert not resto and args[2] == "mcp.consultar_sql"
    assert "Límite de uso" in _detalle(auditoria)["error"]


@pytest.mark.usefixtures("token")
async def test_rate_limit_por_dia(limiter: LimiterFalso, servidor: Any) -> None:
    limiter.deniega = {"dia"}
    with pytest.raises(ToolError) as exc:
        await servidor.call_tool("describir_esquema", {})
    assert str(exc.value) == "Límite de uso alcanzado\nPista: inténtalo mañana"


@pytest.mark.usefixtures("token")
async def test_sql_enorme_rechazado_se_audita_recortado_y_cuenta(
    limiter: LimiterFalso, auditoria: list[Any], servidor: Any
) -> None:
    """Lo que el esquema rechaza también cuenta para el límite y no llena ``audit_log``."""
    with pytest.raises(ToolError) as exc:
        await servidor.call_tool("consultar_sql", {"sql": "S" * 30_000})
    assert str(exc.value).startswith("Argumentos no válidos: sql:")
    assert limiter.llamadas == [("mcp:min:7", 60, 60), ("mcp:dia:7", 1000, 86400)]
    (args, _), *resto = auditoria
    assert not resto and args[2] == "mcp.consultar_sql"
    assert len(args[3]) <= envoltura.MAX_CHARS_DETALLE
    sql = _detalle(auditoria)["args"]["sql"]
    assert sql == "S" * 20_000 + "…[+10000]"


@pytest.mark.usefixtures("token")
async def test_tool_desconocida_se_audita_y_cuenta(
    limiter: LimiterFalso, auditoria: list[Any], servidor: Any
) -> None:
    with pytest.raises(ToolError) as exc:
        await servidor.call_tool("borrar_todo", {"x": 1})
    assert "No existe la herramienta 'borrar_todo'" in str(exc.value)
    assert "consultar_sql" in str(exc.value)
    assert [k for k, *_ in limiter.llamadas] == ["mcp:min:7", "mcp:dia:7"]
    (args, _), *_ = auditoria
    # El nombre lo elige el cliente: no se usa como `action`.
    assert args[2] == "mcp.tool_desconocida"
    assert _detalle(auditoria)["args"] == {"tool": "borrar_todo", "argumentos": {"x": 1}}


@pytest.mark.usefixtures("token")
async def test_el_detail_entero_tiene_tope(auditoria: list[Any]) -> None:
    await envoltura.auditar_rechazo(
        "buscar_licitaciones", {"a": "a" * 20_000, "b": ['"' * 20_000]}, "e"
    )
    (args, _), *_ = auditoria
    assert len(args[3]) <= envoltura.MAX_CHARS_DETALLE
    recortados = _detalle(auditoria)["args"]
    assert isinstance(recortados, str) and recortados.endswith("]")
    assert "…[+" in recortados


@pytest.mark.usefixtures("token", "limiter")
async def test_la_auditoria_sobrevive_a_la_cancelacion(auditoria: list[Any]) -> None:
    import time as reloj

    import anyio

    def lenta() -> dict[str, Any]:
        reloj.sleep(0.3)
        return {"n_filas": 0}

    tool = envoltura.herramienta("describir_esquema", lenta)
    with anyio.move_on_after(0.05):
        await tool()
    # El cliente cortó a mitad: lo ejecutado queda auditado igual.
    (args, _), *_ = auditoria
    assert args[2] == "mcp.describir_esquema"


@pytest.mark.usefixtures("token", "limiter")
async def test_excepcion_inesperada_no_filtra_traza(
    auditoria: list[Any], caplog: pytest.LogCaptureFixture
) -> None:
    def rota() -> dict[str, Any]:
        raise RuntimeError("secreto interno: postgres://u:p@h/db")

    tool = envoltura.herramienta("describir_esquema", rota)
    with pytest.raises(ToolError) as exc:
        await tool()

    mensaje = str(exc.value)
    assert mensaje == "Error interno; revisa los logs del servidor"
    assert "Traceback" not in mensaje and "secreto" not in mensaje
    assert exc.value.__cause__ is None and exc.value.__suppress_context__
    assert _detalle(auditoria)["error"] == "interno: RuntimeError"


@pytest.mark.usefixtures("token", "limiter", "auditoria")
async def test_error_herramienta_con_pista() -> None:
    def no_existe(id_externo: str) -> dict[str, Any]:
        raise ErrorHerramienta("No existe la licitación 'x'.", "búscala con buscar_licitaciones")

    tool = envoltura.herramienta("ficha_licitacion", no_existe)
    with pytest.raises(ToolError) as exc:
        await tool(id_externo="x")
    assert str(exc.value) == "No existe la licitación 'x'.\nPista: búscala con buscar_licitaciones"


@pytest.mark.usefixtures("token", "limiter")
async def test_validation_error_lista_compacta_de_campos(auditoria: list[Any]) -> None:
    tool = envoltura.herramienta("buscar_licitaciones", buscar_licitaciones)
    with pytest.raises(ToolError) as exc:
        await tool(texto="x", desde="15/10/2026", limite=20)
    mensaje = str(exc.value)
    assert mensaje.startswith("Argumentos no válidos:")
    assert "desde: la fecha debe tener el formato YYYY-MM-DD" in mensaje
    assert "errors.pydantic.dev" not in mensaje and "input_value" not in mensaje
    assert "desde" in _detalle(auditoria)["error"]


@pytest.mark.usefixtures("limiter")
async def test_sin_token_es_error_de_tool(
    monkeypatch: pytest.MonkeyPatch, auditoria: list[Any]
) -> None:
    monkeypatch.setattr(envoltura, "get_access_token", lambda: None)
    llamadas: list[int] = []
    tool = envoltura.herramienta("describir_esquema", lambda: llamadas.append(1) or {})
    with pytest.raises(ToolError, match="autentic"):
        await tool()
    assert llamadas == []
    (args, kwargs), *_ = auditoria
    assert args[0] == "anon" and kwargs == {"user_id": None}


def test_conserva_firma_y_documentacion() -> None:
    tool = envoltura.herramienta("buscar_licitaciones", buscar_licitaciones)
    firma = inspect.signature(tool, eval_str=True)
    original = inspect.signature(buscar_licitaciones, eval_str=True)
    assert list(firma.parameters) == list(original.parameters)
    assert firma.parameters["limite"].default == 20
    assert firma.return_annotation is CallToolResult
    assert tool.__doc__ == buscar_licitaciones.__doc__
    assert inspect.iscoroutinefunction(tool)


@pytest.mark.usefixtures("token", "limiter")
async def test_n_filas_de_las_tools_de_dominio(auditoria: list[Any]) -> None:
    tool = envoltura.herramienta("buscar_en_pliegos", lambda: {"fragmentos": [{}, {}, {}]})
    await tool()
    tool = envoltura.herramienta("buscar_licitaciones", lambda: {"total": 9, "resultados": [{}]})
    await tool()
    tool = envoltura.herramienta("ficha_licitacion", lambda: {"licitacion": {}})
    await tool()
    n_filas = [json.loads(args[3])["n_filas"] for args, _ in auditoria]
    assert n_filas == [3, 1, None]


# ---------------------------------------------------------------------------
# Configuración y arranque
# ---------------------------------------------------------------------------

_VARIABLES = (
    "MCP_DATABASE_URL",
    "MCP_PUBLIC_URL",
    "MCP_GOOGLE_REDIRECT_URI",
    "DATABASE_URL",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "SIGNING_KEY",
)


def _vaciar_configuracion(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from config import settings

    for var in ("MCP_DATABASE_URL", "MCP_PUBLIC_URL", "MCP_GOOGLE_REDIRECT_URI"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", SecretStr(""))
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", SecretStr(""))
    monkeypatch.setattr(settings, "SIGNING_KEY", SecretStr(""))


def test_falta_config_en_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from config import settings
    from mcp_server.servidor import validar_configuracion

    _vaciar_configuracion(monkeypatch)
    assert validar_configuracion() == list(_VARIABLES)

    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.com")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "SIGNING_KEY", SecretStr("k" * 40))
    assert validar_configuracion() == [
        "MCP_DATABASE_URL",
        "MCP_GOOGLE_REDIRECT_URI",
        "DATABASE_URL",
        "GOOGLE_CLIENT_SECRET",
    ]


def test_config_redirect_de_google_y_https_en_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from config import settings
    from mcp_server.servidor import validar_configuracion

    _vaciar_configuracion(monkeypatch)
    monkeypatch.setenv("MCP_DATABASE_URL", "postgresql://mcp@h/db")
    monkeypatch.setattr(settings, "DATABASE_URL", SecretStr("postgresql://app@h/db"))
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", SecretStr("s"))
    monkeypatch.setattr(settings, "SIGNING_KEY", SecretStr("k" * 40))
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.com/")
    monkeypatch.setenv("MCP_GOOGLE_REDIRECT_URI", "https://mcp.example.com/oauth/google/callback")
    monkeypatch.setattr(settings, "ENV", "prod")
    assert validar_configuracion() == []

    monkeypatch.setenv("MCP_GOOGLE_REDIRECT_URI", "https://otro.example.com/callback")
    assert validar_configuracion() == [
        "MCP_GOOGLE_REDIRECT_URI (debe ser https://mcp.example.com/oauth/google/callback)"
    ]

    monkeypatch.setenv("MCP_PUBLIC_URL", "http://mcp.example.com")
    monkeypatch.setenv("MCP_GOOGLE_REDIRECT_URI", "http://mcp.example.com/oauth/google/callback")
    assert validar_configuracion() == ["MCP_PUBLIC_URL (debe ser https:// en prod)"]
    # En desarrollo el http (localhost) es lo normal.
    monkeypatch.setattr(settings, "ENV", "dev")
    assert validar_configuracion() == []


def test_main_aborta_en_prod_si_falta_config(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from config import settings
    from mcp_server import __main__ as principal

    _vaciar_configuracion(monkeypatch)
    monkeypatch.setattr(settings, "ENV", "prod")
    arrancado: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: arrancado.append(a))
    with pytest.raises(SystemExit) as exc:
        principal.main()
    assert "MCP_PUBLIC_URL" in str(exc.value) and "SIGNING_KEY" in str(exc.value)
    assert arrancado == []


def test_main_arranca_uvicorn_en_el_puerto(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from config import settings
    from mcp_server import __main__ as principal

    _vaciar_configuracion(monkeypatch)
    monkeypatch.setattr(settings, "ENV", "dev")
    monkeypatch.setenv("PORT", "9123")
    arrancado: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **k: arrancado.append(k))
    principal.main()
    assert arrancado[0]["host"] == "0.0.0.0" and arrancado[0]["port"] == 9123  # noqa: S104


def test_callback_de_google_redirige_al_cliente_sin_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from starlette.testclient import TestClient

    from mcp_server.auth.proveedor import ProveedorTenderFlow
    from mcp_server.servidor import crear_servidor

    recibido: list[tuple[str, str | None, str | None]] = []

    class ProveedorFalso(ProveedorTenderFlow):
        async def completar_login(self, state: str, code: str | None, error: str | None) -> str:
            recibido.append((state, code, error))
            return "http://localhost:3000/cb?code=c0d1g0&state=s"

    monkeypatch.setenv("MCP_PUBLIC_URL", "http://localhost:8080")
    falso = ProveedorFalso(almacen=None, google=None)  # type: ignore[arg-type]  # no se usan
    app = crear_servidor(falso).streamable_http_app(json_response=True, stateless_http=True)
    r = TestClient(app).get(
        "/oauth/google/callback", params={"state": "st", "code": "g"}, follow_redirects=False
    )
    assert r.status_code == 302
    assert r.headers["location"] == "http://localhost:3000/cb?code=c0d1g0&state=s"
    assert r.headers["cache-control"] == "no-store"
    assert recibido == [("st", "g", None)]
