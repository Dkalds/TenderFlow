"""Ejecutor de SQL libre del MCP interno: un ``SELECT`` escrito por un LLM.

La frontera de seguridad **no** está en este módulo sino en el rol de Postgres
``tenderflow_mcp`` (``mcp_server/catalogo.py``): solo ``SELECT`` por tabla y
columna visibles, ``default_transaction_read_only = on``, ``statement_timeout``,
``NOBYPASSRLS`` y ``CONNECTION LIMIT 5``. Aquí no se intenta «validar» el SQL
(un parser casero sería una falsa garantía); solo se acota lo que vuelve:

* un único statement: el SQL se envuelve en ``SELECT * FROM (…) AS q LIMIT %s``
  y se ejecuta **con un parámetro enlazado**, lo que obliga a psycopg a usar el
  protocolo extendido, que rechaza varios comandos (``42601``). Sin parámetros
  usaría el protocolo simple y un ``SELECT 1) AS x; DROP …; SELECT (1`` se
  saldría del envoltorio. Por eso cada ``%`` del SQL del usuario se duplica;
* a lo sumo ``MAX_FILAS`` filas (se pide una de más para detectar truncado);
* celdas de texto recortadas a ``MAX_CHARS_CELDA`` y respuesta serializada de
  como mucho ``MAX_CHARS_RESPUESTA`` caracteres (se quitan filas del final).

El pool es propio y perezoso (la conexión es otro usuario, con otra URL) y no
reutiliza los pools de la aplicación. Los límites de tiempo los fija el rol; por
eso se retiran de las opciones de arranque los ``statement_timeout`` e
``idle_in_transaction_session_timeout`` que ``_pg_connect_kwargs`` añade para
los pools de la app: una opción de arranque gana al ``ALTER ROLE … SET`` y
pisaría los 15 s del rol con los 30 s de la aplicación.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as hora
from decimal import Decimal
from types import MappingProxyType
from typing import TypeAlias
from uuid import UUID

import psycopg
from psycopg_pool import ConnectionPool

from config.settings import mcp_database_url
from db.connection import _pg_connect_kwargs

__all__ = [
    "MAX_CHARS_CELDA",
    "MAX_CHARS_RESPUESTA",
    "MAX_CHARS_SQL",
    "MAX_FILAS",
    "PISTAS",
    "ErrorConsulta",
    "JSONValue",
    "ResultadoConsulta",
    "cerrar_pool_mcp",
    "ejecutar_select",
    "envolver",
    "normalizar_sql",
    "serializar_valor",
]

JSONValue: TypeAlias = bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"] | None

MAX_FILAS = 500
MAX_CHARS_CELDA = 1_000
MAX_CHARS_SQL = 20_000
MAX_CHARS_RESPUESTA = 100_000

#: Tamaño máximo del pool: coincide con ``CONNECTION LIMIT 5`` del rol.
_POOL_MAX = 5
#: Segundos que se espera una conexión libre antes de rendirse.
_POOL_TIMEOUT = 10.0

PISTAS: Mapping[str, str] = MappingProxyType(
    {
        "42P01": "La tabla no existe o no es visible. Usa listar_tablas para ver las disponibles.",
        "42703": "La columna no existe. Usa describir_tabla para ver las columnas de la tabla.",
        "57014": (
            "La consulta superó el tiempo máximo. Acótala con WHERE/LIMIT, "
            "evita productos cartesianos y filtra primero por fechas o claves."
        ),
        "42501": (
            "Permiso denegado: la tabla o la columna no es visible para el MCP "
            "(credenciales y secretos están excluidos). Pide solo columnas "
            "concretas; SELECT * no funciona en tablas con columnas ocultas."
        ),
        "25006": "Solo se permiten consultas de lectura (SELECT / WITH … SELECT).",
        "42601": (
            "Error de sintaxis o varias sentencias. Envía una sola sentencia SELECT, "
            "sin punto y coma intermedios."
        ),
    }
)


class ErrorConsulta(Exception):
    """Error al ejecutar la consulta, con un mensaje apto para devolver al LLM."""

    def __init__(self, sqlstate: str | None, mensaje: str, pista: str | None = None) -> None:
        super().__init__(mensaje)
        self.sqlstate = sqlstate
        self.mensaje = mensaje
        self.pista = pista


@dataclass(frozen=True)
class ResultadoConsulta:
    columnas: list[str]
    filas: list[list[JSONValue]]
    n_filas: int
    truncado: bool
    duracion_ms: int

    def como_dict(self) -> dict[str, JSONValue]:
        columnas: list[JSONValue] = list(self.columnas)
        filas: list[JSONValue] = list(self.filas)
        return {
            "columnas": columnas,
            "filas": filas,
            "n_filas": self.n_filas,
            "truncado": self.truncado,
            "duracion_ms": self.duracion_ms,
        }


# ── Normalización y envoltorio ─────────────────────────────────────────────


#: ``;`` final seguido solo de espacios, comentarios ``-- …`` o ``/* … */`` (y más
#: ``;``). Sólo se mira la cola: no se interpretan comentarios ni literales en el
#: resto del SQL. Un ``;`` dentro de un literal o de un comentario no encaja
#: porque lo que sigue (la comilla o el ``*/``) no pertenece a ninguna
#: alternativa. ``\s`` suelto, sin ``+``: evita el retroceso exponencial.
_COLA_VACIA = re.compile(r";(?:\s|;|--[^\n]*|/\*(?:(?!\*/).)*\*/)*\Z", re.DOTALL)


def normalizar_sql(sql: str) -> str:
    """Quita espacios y la cola ``; …`` (con comentarios); rechaza lo vacío o largo."""
    if len(sql) > 2 * MAX_CHARS_SQL:  # tope barato antes de aplicar la regex
        raise ErrorConsulta(
            None,
            f"La consulta tiene {len(sql)} caracteres; el máximo es {MAX_CHARS_SQL}.",
            "Simplifica la consulta o divídela en varias.",
        )
    limpio = sql.strip()
    cola = _COLA_VACIA.search(limpio)
    if cola is not None:
        limpio = limpio[: cola.start()].rstrip()
    if not limpio:
        raise ErrorConsulta(None, "La consulta está vacía.", None)
    if len(limpio) > MAX_CHARS_SQL:
        raise ErrorConsulta(
            None,
            f"La consulta tiene {len(limpio)} caracteres; el máximo es {MAX_CHARS_SQL}.",
            "Simplifica la consulta o divídela en varias.",
        )
    return limpio


def envolver(sql: str, max_filas: int) -> str:
    """Envuelve ``sql`` para acotar las filas; el ``LIMIT`` va como parámetro ``%s``.

    Los saltos de línea evitan que un ``-- comentario`` final se coma el
    paréntesis de cierre. Los ``%`` del usuario se duplican porque la sentencia
    se ejecuta con parámetros (protocolo extendido); ``max_filas`` no se
    interpola: lo enlaza ``ejecutar_select`` como ``max_filas + 1``.
    """
    # No es el escapado de comodines LIKE de ``db/sql_fragments.py``: duplica
    # ``%`` para el formato de psycopg. ``split/join`` evita que el ratchet de
    # ``test_escape_like`` lo confunda con una segunda copia de ese escapado.
    literal = "%%".join(sql.split("%"))
    return f"SELECT * FROM (\n{literal}\n) AS q LIMIT %s"


# ── Serialización ──────────────────────────────────────────────────────────


def _recortar(texto: str) -> str:
    if len(texto) <= MAX_CHARS_CELDA:
        return texto
    return f"{texto[:MAX_CHARS_CELDA]}…[+{len(texto) - MAX_CHARS_CELDA}]"


def _iso_intervalo(td: timedelta) -> str:
    signo = "-" if td < timedelta(0) else ""
    td = abs(td)
    horas, resto = divmod(td.seconds, 3600)
    minutos, segundos = divmod(resto, 60)
    partes_fecha = f"{td.days}D" if td.days else ""
    partes_hora = ""
    if horas:
        partes_hora += f"{horas}H"
    if minutos:
        partes_hora += f"{minutos}M"
    if segundos or td.microseconds:
        frac = f"{td.microseconds:06d}".rstrip("0")
        partes_hora += f"{segundos}.{frac}S" if frac else f"{segundos}S"
    if not partes_fecha and not partes_hora:
        partes_hora = "0S"
    return f"{signo}P{partes_fecha}" + (f"T{partes_hora}" if partes_hora else "")


def serializar_valor(v: object) -> JSONValue:
    """Convierte un valor devuelto por psycopg en JSON sin tumbar la tool.

    ``NaN``/``Infinity`` y los binarios (``bytea``) pasan a ``None``; fechas,
    ``uuid`` y el resto de tipos sin representación JSON caen a texto.
    """
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, Decimal):
        return float(v) if v.is_finite() else None
    if isinstance(v, str):
        return _recortar(v)
    if isinstance(v, bytes | bytearray | memoryview):
        return None
    if isinstance(v, datetime | date | hora):
        return v.isoformat()
    if isinstance(v, timedelta):
        return _iso_intervalo(v)
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, list | tuple):
        return [serializar_valor(x) for x in v]
    if isinstance(v, dict):
        return {_recortar(str(k)): serializar_valor(x) for k, x in v.items()}
    return _recortar(str(v))


def _acotar_respuesta(
    columnas: list[str], filas: list[list[JSONValue]], truncado: bool, duracion_ms: int
) -> ResultadoConsulta:
    """Quita filas del final hasta que la respuesta serializada cabe en el tope."""

    def construir(n: int, trunc: bool) -> ResultadoConsulta:
        return ResultadoConsulta(columnas, filas[:n], n, trunc, duracion_ms)

    n = len(filas)
    base = len(json.dumps(construir(0, True).como_dict()))
    if base > MAX_CHARS_RESPUESTA:
        # Sólo ocurriría con cientos de columnas de nombre enorme: sin filas no
        # hay nada que quitar, así que se devuelve lo que hay.
        return construir(0, True)
    acumulado = base
    cabe = 0
    for fila in filas:
        acumulado += len(json.dumps(fila)) + 2  # separador ", "
        if acumulado > MAX_CHARS_RESPUESTA:
            break
        cabe += 1
    if cabe < n:
        n, truncado = cabe, True
    # Verificación final con la medida real (los cálculos de arriba son una
    # cota; si se quedara corta se sigue quitando).
    while n > 0 and len(json.dumps(construir(n, truncado).como_dict())) > MAX_CHARS_RESPUESTA:
        n -= 1
        truncado = True
    return construir(n, truncado)


# ── Pool ───────────────────────────────────────────────────────────────────

_pool: ConnectionPool | None = None
_pool_url = ""
_pool_lock = threading.Lock()

_TIMEOUTS_DE_LA_APP = re.compile(
    r"-c\s*(?:statement_timeout|idle_in_transaction_session_timeout)=\S+\s*"
)


def _conn_kwargs(url: str) -> dict[str, object]:
    kwargs: dict[str, object] = dict(_pg_connect_kwargs(url, read_only=True))
    opciones = kwargs.get("options")
    if isinstance(opciones, str):
        sin_timeouts = _TIMEOUTS_DE_LA_APP.sub("", opciones).strip()
        if sin_timeouts:
            kwargs["options"] = sin_timeouts
        else:
            kwargs.pop("options")
    return kwargs


def _reiniciar_sesion(conn: psycopg.Connection[tuple[object, ...]]) -> None:
    """Deja la conexión como recién abierta antes de devolverla al pool.

    ``default_transaction_read_only``, ``statement_timeout``,
    ``idle_in_transaction_session_timeout`` y ``work_mem`` son modificables por
    el usuario de la sesión: ``SELECT set_config('statement_timeout', '0', false)``
    es un SELECT legal y sin reinicio el cambio persistiría para el siguiente
    que use la conexión. ``RESET ALL`` devuelve cada parámetro a su valor de
    arranque (el ``ALTER ROLE … SET`` del rol más las opciones de conexión) y los
    bloqueos de aviso de sesión se sueltan aparte. No se usa ``DISCARD ALL``:
    borraría los statements preparados que psycopg cree tener. Si esto falla,
    el pool descarta la conexión.
    """
    conn.execute("RESET ALL")
    conn.execute("SELECT pg_advisory_unlock_all()")


def _get_pool(url: str) -> ConnectionPool:
    """Pool perezoso por ``MCP_DATABASE_URL``; si la URL cambia se reconstruye."""
    global _pool, _pool_url
    with _pool_lock:
        if _pool is not None and _pool_url == url:
            return _pool
        if _pool is not None:
            _pool.close()
            _pool = None
        try:
            _pool = ConnectionPool(
                conninfo=url,
                min_size=min(1, _POOL_MAX),
                max_size=_POOL_MAX,
                kwargs=_conn_kwargs(url),
                reset=_reiniciar_sesion,
                timeout=_POOL_TIMEOUT,
                check=ConnectionPool.check_connection,
                open=True,
                name="tenderflow-mcp",
            )
        except Exception as exc:
            from observability.logging import redact_dsn

            raise ErrorConsulta(
                None, f"No se pudo abrir el pool del MCP: {redact_dsn(str(exc))}", None
            ) from None
        _pool_url = url
        return _pool


def cerrar_pool_mcp() -> None:
    """Cierra el pool del MCP si está abierto (tests y apagado del servidor)."""
    global _pool, _pool_url
    with _pool_lock:
        pool, _pool, _pool_url = _pool, None, ""
    if pool is not None:
        pool.close()


# ── Ejecución ──────────────────────────────────────────────────────────────


def _traducir(exc: psycopg.Error) -> ErrorConsulta:
    sqlstate = exc.sqlstate
    primario = exc.diag.message_primary or str(exc)
    primera_linea = primario.strip().splitlines()[0] if primario.strip() else type(exc).__name__
    return ErrorConsulta(sqlstate, primera_linea, PISTAS.get(sqlstate) if sqlstate else None)


def ejecutar_select(sql: str, *, max_filas: int = MAX_FILAS) -> ResultadoConsulta:
    """Ejecuta ``sql`` con el rol MCP y devuelve filas serializadas y acotadas."""
    url = mcp_database_url()
    if not url:
        raise ErrorConsulta(None, "MCP_DATABASE_URL no configurada", None)
    envuelta = envolver(normalizar_sql(sql), max_filas)
    pool = _get_pool(url)
    inicio = time.perf_counter()
    try:
        with pool.connection() as conn:
            cur = conn.execute(envuelta, (max_filas + 1,))
            columnas = [str(d.name) for d in (cur.description or [])]
            crudas = cur.fetchall()
    except psycopg.Error as exc:
        raise _traducir(exc) from None
    duracion_ms = int((time.perf_counter() - inicio) * 1000)
    truncado = len(crudas) > max_filas
    filas = [[serializar_valor(v) for v in fila] for fila in crudas[:max_filas]]
    return _acotar_respuesta(columnas, filas, truncado, duracion_ms)
