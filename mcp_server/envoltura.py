"""Envoltura común de las tools del MCP: identidad, rate limit, auditoría y errores.

Las tools de ``mcp_server/tools/`` son funciones síncronas y puras sobre ``db/``
y ``services/``; :func:`herramienta` les pone lo que exige el servidor:

1. **Identidad**: ``user_id`` sale del ``subject`` del access token que validó
   el middleware del SDK (``get_access_token``). Sin token no se ejecuta nada.
2. **Rate limit** por usuario (``services.rate_limiting``): 60 llamadas por
   minuto (``mcp:min:<id>``) y 1 000 por día (``mcp:dia:<id>``). Lo aplica
   :func:`limitar_llamada`, que el servidor llama al entrar en ``call_tool``
   para que cuente **cada intento**, también los que el SDK rechaza antes de
   llegar a la tool (argumentos fuera de esquema, tool inexistente).
3. **Ejecución** en el threadpool (``anyio.to_thread``): las tools hacen E/S
   bloqueante (psycopg) y no pueden ocupar el bucle de eventos.
4. **Auditoría siempre**, también si la llamada falla o la corta el límite
   (las denegaciones por límite, una fila por usuario, ventana y minuto):
   ``audit_log`` con ``action = "mcp.<tool>"`` y en ``detail`` los argumentos
   (el SQL entero hasta 20 000 caracteres; cada texto se recorta ahí con la
   marca ``…[+N]`` y el ``detail`` completo a 25 000), ``n_filas``,
   ``duracion_ms`` y ``error``. La escritura está blindada frente a la
   cancelación. Pasa por ``auditar_oauth``, la única llamada a ``log_action``
   del MCP (ruling R12).
5. **Log** ``mcp_tool`` con la tool, el usuario, la duración y si fue bien; ni
   argumentos ni filas (eso es de la auditoría).
6. **Errores para el LLM**: ``ErrorHerramienta`` y ``ErrorConsulta`` salen como
   ``ToolError`` con ``"{mensaje}\\nPista: {pista}"``; una ``ValidationError`` de
   los modelos de entrada, como lista compacta de campos; cualquier otra cosa
   se registra con traza en el log y sale como un mensaje genérico, sin ella.

La salida va dos veces, como pide la especificación MCP: ``structuredContent``
(el dict) y un bloque de texto con el mismo JSON compacto, para los clientes que
solo leen ``content``.
"""

from __future__ import annotations

import functools
import inspect
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ParamSpec

import anyio
import anyio.to_thread
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent
from pydantic import ValidationError

from db.consulta_libre import MAX_CHARS_SQL, ErrorConsulta, JSONValue
from mcp_server.auth.proveedor import auditar_oauth
from mcp_server.tools import ErrorHerramienta
from mcp_server.tools.consulta import error_de_consulta
from observability.logging import get_logger
from services.rate_limiting import get_rate_limiter

__all__ = [
    "ERROR_INTERNO",
    "LIMITES",
    "auditar_rechazo",
    "herramienta",
    "limitar_llamada",
    "resumir_validacion",
]

log = get_logger(__name__)

P = ParamSpec("P")

#: ``(ventana, máximo de llamadas, segundos, pista)`` por usuario (Global Constraints).
LIMITES: tuple[tuple[str, int, int, str], ...] = (
    ("min", 60, 60, "espera 60 s"),
    ("dia", 1_000, 86_400, "inténtalo mañana"),
)
ERROR_INTERNO = "Error interno; revisa los logs del servidor"
#: Tope de cada texto auditado (argumento o error): el del SQL que admite el esquema.
MAX_CHARS_AUDITADO = MAX_CHARS_SQL
#: Tope del ``detail`` entero: un SQL máximo más los metadatos, con holgura.
MAX_CHARS_DETALLE = 25_000
#: Segundos durante los que no se vuelve a auditar la denegación por límite de
#: un mismo usuario en una misma ventana (cada una sigue en el log, a ``debug``).
SILENCIO_DENEGACIONES_S = 60

#: Reloj de las marcas de denegación (inyectable en los tests).
_reloj = time.monotonic
#: ``(user_id, ventana)`` → hasta cuándo no se vuelve a auditar su denegación.
_denegaciones_auditadas: dict[tuple[int, str], float] = {}


def _recortar(texto: str, maximo: int) -> str:
    """``texto`` hasta ``maximo`` caracteres, con la marca ``…[+N]`` de lo que se quitó."""
    if len(texto) <= maximo:
        return texto
    return f"{texto[:maximo]}…[+{len(texto) - maximo}]"


def _acotar(valor: object) -> object:
    """Recorta cada texto de un argumento (también dentro de listas y objetos)."""
    if isinstance(valor, str):
        return _recortar(valor, MAX_CHARS_AUDITADO)
    if isinstance(valor, Mapping):
        return {_recortar(str(k), 200): _acotar(v) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_acotar(v) for v in valor]
    return valor


def resumir_validacion(exc: ValidationError) -> str:
    """``campo: motivo; …`` sin valores, tipos internos ni enlaces a la documentación."""
    partes: list[str] = []
    for err in exc.errors(include_url=False, include_input=False, include_context=False):
        campo = ".".join(str(p) for p in err["loc"]) or "entrada"
        partes.append(f"{campo}: {err['msg'].removeprefix('Value error, ')}")
    return "Argumentos no válidos: " + "; ".join(partes)


def _texto_herramienta(exc: ErrorHerramienta) -> str:
    return exc.mensaje if exc.pista is None else f"{exc.mensaje}\nPista: {exc.pista}"


def _usuario() -> int:
    """``users.id`` del access token de la petición."""
    acceso = get_access_token()
    if acceso is None or not acceso.subject:
        # En producción el middleware de auth del SDK no deja llegar aquí sin token.
        raise ErrorHerramienta(
            "Petición sin autenticar.", "conecta el servidor con OAuth (login de Google)"
        )
    try:
        return int(acceso.subject)
    except ValueError:
        raise ErrorHerramienta(
            "Token sin usuario válido.", "vuelve a conectar el servidor"
        ) from None


def _usuario_o_none() -> int | None:
    try:
        return _usuario()
    except ErrorHerramienta:
        return None


async def _limitar(user_id: int) -> tuple[str, ErrorHerramienta] | None:
    """La primera ventana que se supera y su error, o ``None`` si la llamada cabe."""
    limiter = get_rate_limiter()
    for ventana, maximo, segundos, pista in LIMITES:
        clave = f"mcp:{ventana}:{user_id}"
        # `check` hace E/S (Redis o Postgres): al threadpool, como el resto.
        permitido = await anyio.to_thread.run_sync(
            functools.partial(limiter.check, clave, max_calls=maximo, window_seconds=segundos)
        )
        if not permitido:
            return ventana, ErrorHerramienta("Límite de uso alcanzado", pista)
    return None


def _auditar_denegacion(user_id: int, ventana: str) -> bool:
    """¿Se audita esta denegación? Una por usuario y ventana cada :data:`SILENCIO_DENEGACIONES_S`.

    Marca en memoria del proceso: un cliente que reintenta en bucle contra el
    límite escribiría una fila de ``audit_log`` por intento.
    """
    ahora = _reloj()
    for marca, hasta in list(_denegaciones_auditadas.items()):
        if hasta <= ahora:
            del _denegaciones_auditadas[marca]
    if (user_id, ventana) in _denegaciones_auditadas:
        return False
    _denegaciones_auditadas[(user_id, ventana)] = ahora + SILENCIO_DENEGACIONES_S
    return True


async def limitar_llamada(nombre: str, argumentos: Mapping[str, Any]) -> None:
    """Rate limit de **cada intento** de llamada, antes de cualquier otro trabajo.

    La llama el servidor al entrar en ``call_tool``, antes de que el SDK busque
    la tool o compruebe los argumentos: una llamada rechazada por el esquema o a
    una tool que no existe también cuenta (y escribe en la auditoría). Si se
    supera el límite sale como ``ToolError``; la denegación se audita una vez
    por usuario, ventana y minuto (:func:`_auditar_denegacion`) y cada una va al
    log. Sin usuario no hace nada: la tool (:func:`herramienta`) lo rechaza y
    lo audita.
    """
    user_id = _usuario_o_none()
    if user_id is None:
        return
    denegada = await _limitar(user_id)
    if denegada is None:
        return
    ventana, exc = denegada
    error = _texto_herramienta(exc)
    if _auditar_denegacion(user_id, ventana):
        await _auditar(nombre, user_id, argumentos, None, 0, error)
    else:
        log.debug("mcp_tool_limite", tool=nombre, user_id=user_id, ventana=ventana)
    raise ToolError(error)


def _contar_filas(resultado: Mapping[str, JSONValue]) -> int | None:
    """Filas devueltas, según la forma de cada tool; ``None`` si no aplica."""
    n = resultado.get("n_filas")
    if isinstance(n, int) and not isinstance(n, bool):
        return n
    for clave in ("resultados", "fragmentos"):
        lista = resultado.get(clave)
        if isinstance(lista, list):
            return len(lista)
    return None


def _respuesta(resultado: Mapping[str, JSONValue]) -> CallToolResult:
    texto = json.dumps(resultado, ensure_ascii=False, separators=(",", ":"))
    return CallToolResult(
        content=[TextContent(type="text", text=texto)], structured_content=dict(resultado)
    )


async def _auditar(
    nombre: str,
    user_id: int | None,
    argumentos: Mapping[str, object],
    n_filas: int | None,
    duracion_ms: int,
    error: str | None,
) -> None:
    # Ida y vuelta por JSON con `default=str`: un argumento que el SDK no validó
    # (llamada rechazada) puede no ser serializable tal cual. Cada texto se
    # recorta: el SDK admite cuerpos de hasta 4 MiB y lo rechazado por el
    # esquema (un `sql` de 30 000 caracteres) también se audita.
    args = _acotar(json.loads(json.dumps(dict(argumentos), ensure_ascii=False, default=str)))
    detalle: dict[str, object] = {
        "args": args,
        "n_filas": n_filas,
        "duracion_ms": duracion_ms,
        "error": None if error is None else _recortar(error, 1_000),
    }
    if len(json.dumps(detalle, ensure_ascii=False)) > MAX_CHARS_DETALLE:
        # Muchos argumentos largos a la vez: los args pasan a ser su JSON recortado
        # (se reduce hasta caber, porque el escapado de comillas también ocupa).
        crudo = json.dumps(args, ensure_ascii=False)
        maximo = MAX_CHARS_DETALLE
        while True:
            detalle["args"] = _recortar(crudo, maximo)
            if maximo == 0 or len(json.dumps(detalle, ensure_ascii=False)) <= MAX_CHARS_DETALLE:
                break
            maximo //= 2
    # Blindado frente a la cancelación: si el cliente corta a mitad de la
    # llamada, la auditoría de lo que ya se ejecutó se escribe igual.
    with anyio.CancelScope(shield=True):
        await anyio.to_thread.run_sync(auditar_oauth, f"mcp.{nombre}", user_id, detalle)
    log.info("mcp_tool", tool=nombre, user_id=user_id, duracion_ms=duracion_ms, ok=error is None)


async def auditar_rechazo(nombre: str, argumentos: Mapping[str, Any], error: str) -> None:
    """Audita una llamada que el SDK rechazó sin llegar a :func:`herramienta`.

    Argumentos que no casan con el esquema o una tool que no existe: el SDK lo
    decide antes de llamar a la tool, así que la llama el servidor.
    """
    await _auditar(nombre, _usuario_o_none(), argumentos, None, 0, error)


def herramienta(
    nombre: str, fn: Callable[P, Mapping[str, JSONValue]]
) -> Callable[P, Awaitable[CallToolResult]]:
    """Envuelve la tool ``fn`` (síncrona) para registrarla en el servidor como ``nombre``.

    Conserva el nombre, el docstring (la descripción de la tool) y la firma de
    ``fn`` con sus anotaciones evaluadas: el SDK construye con ella el esquema
    JSON de la entrada y valida los argumentos antes de llamar.
    """
    firma = inspect.signature(fn, eval_str=True)

    @functools.wraps(fn)
    async def envuelta(*args: P.args, **kwargs: P.kwargs) -> CallToolResult:
        inicio = time.perf_counter()
        argumentos: dict[str, object] = dict(kwargs)
        user_id: int | None = None
        n_filas: int | None = None
        error: str | None = None
        try:
            argumentos = dict(firma.bind(*args, **kwargs).arguments)
            user_id = _usuario()
            resultado = await anyio.to_thread.run_sync(functools.partial(fn, *args, **kwargs))
            n_filas = _contar_filas(resultado)
            return _respuesta(resultado)
        except ErrorHerramienta as exc:
            error = _texto_herramienta(exc)
            raise ToolError(error) from None
        except ErrorConsulta as exc:
            error = _texto_herramienta(error_de_consulta(exc))
            raise ToolError(error) from None
        except ValidationError as exc:
            error = resumir_validacion(exc)
            raise ToolError(error) from None
        except Exception as exc:
            log.exception("mcp_tool_error_interno", tool=nombre, user_id=user_id)
            error = f"interno: {type(exc).__name__}"
            raise ToolError(ERROR_INTERNO) from None
        finally:
            duracion_ms = int((time.perf_counter() - inicio) * 1000)
            await _auditar(nombre, user_id, argumentos, n_filas, duracion_ms, error)

    # El SDK lee la firma con `inspect.signature(..., eval_str=True)`: se le da
    # la de `fn` ya evaluada (sus módulos usan `from __future__ import
    # annotations`) y con el tipo de retorno real de la envoltura.
    envuelta.__signature__ = firma.replace(  # type: ignore[attr-defined]  # atributo estándar de inspect
        return_annotation=CallToolResult
    )
    return envuelta
