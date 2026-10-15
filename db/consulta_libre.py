"""Ejecutor de SQL libre del MCP interno: un ``SELECT`` escrito por un LLM.

La frontera de seguridad **no** está en este módulo sino en el rol de Postgres
``tenderflow_mcp`` (``mcp_server/catalogo.py``): solo ``SELECT`` por tabla y
columna visibles, ``default_transaction_read_only = on``, ``statement_timeout``,
``NOBYPASSRLS`` y ``CONNECTION LIMIT 5``. Aquí no se intenta «validar» el SQL
(un parser casero sería una falsa garantía); solo se acota lo que vuelve y se
vetan unas pocas funciones (defensa en profundidad, no frontera):

* un único statement: el SQL se envuelve en ``SELECT * FROM (…) AS q LIMIT %s``
  y se ejecuta **con un parámetro enlazado**, lo que obliga a psycopg a usar el
  protocolo extendido, que rechaza varios comandos (``42601``). Sin parámetros
  usaría el protocolo simple y un ``SELECT 1) AS x; DROP …; SELECT (1`` se
  saldría del envoltorio. Por eso cada ``%`` del SQL del usuario se duplica;
* a lo sumo ``MAX_FILAS`` filas (se pide una de más para detectar truncado),
  leídas por lotes con un cursor de servidor que deja de pedir en cuanto la
  respuesta ya no cabe;
* celdas de texto recortadas a ``MAX_CHARS_CELDA`` y respuesta serializada de
  como mucho ``MAX_CHARS_RESPUESTA`` caracteres (se quitan filas del final);
* ninguna llamada a las funciones vetadas (cerrojos de aviso, ``pg_notify``,
  ``set_config``, las que ejecutan SQL en texto…): ver :func:`normalizar_sql`.

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
from collections.abc import Mapping, Sequence
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
    "claves_foraneas_de",
    "columnas_de",
    "ejecutar_select",
    "ejemplo_de",
    "envolver",
    "filas_aproximadas",
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
        "42P01": "La tabla no existe o no es visible. Usa describir_esquema para ver las disponibles.",
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


#: Espacios para el léxico de Postgres (``space`` de ``scan.l``). Un espacio
#: Unicode (U+00A0) no lo es: Postgres lo lee como parte de un identificador.
_ESPACIOS = " \t\n\r\f\v"
_SALTOS = "\n\r"
_ESPACIOS_HORIZONTALES = " \t\f\v"


def _inicio_ident(c: str) -> bool:
    """``ident_start`` de Postgres: letra ASCII, ``_`` o cualquier carácter no ASCII."""
    return ("a" <= c <= "z") or ("A" <= c <= "Z") or c == "_" or ord(c) >= 0x80


def _es_ident(c: str) -> bool:
    """``ident_cont`` de Postgres: ``ident_start``, dígitos y ``$``."""
    return _inicio_ident(c) or ("0" <= c <= "9") or c == "$"


def _etiqueta_dolar(sql: str, i: int) -> str | None:
    """Devuelve ``$tag$`` si en ``sql[i]`` empieza una cadena entre dólares.

    La etiqueta sigue ``dolqdelim`` de Postgres: vacía o un ``ident_start``
    seguido de ``ident_start``/dígitos (sin ``$``).
    """
    n = len(sql)
    j = i + 1
    if j < n and _inicio_ident(sql[j]):
        j += 1
        while j < n and (_inicio_ident(sql[j]) or "0" <= sql[j] <= "9"):
            j += 1
    if j < n and sql[j] == "$":
        return sql[i : j + 1]
    return None


def _continua_literal(sql: str, j: int) -> int | None:
    """Si tras un literal cerrado en ``j`` viene su continuación, el índice de su ``'``.

    Postgres une ``'a'`` y ``'b'`` separados por espacios con **al menos un
    salto de línea** (y comentarios ``--``) en un único literal, en el mismo
    modo que el primero (``quotecontinue`` de ``scan.l``). Un ``/* */`` corta.
    """
    n = len(sql)
    salto = False
    while j < n:
        c = sql[j]
        if c in _SALTOS:
            salto = True
            j += 1
        elif c in _ESPACIOS_HORIZONTALES:
            j += 1
        elif sql.startswith("--", j):
            while j < n and sql[j] not in _SALTOS:
                j += 1
        else:
            break
    return j if salto and j < n and sql[j] == "'" else None


def _fin_literal(sql: str, i: int, escapes: bool) -> int | None:
    """Índice tras el literal ``'…'`` que abre ``sql[i]``; ``None`` si no se cierra.

    ``''`` es una comilla dentro del literal; con ``escapes`` (``E'…'``) la
    barra invertida escapa el carácter siguiente. Sigue en las continuaciones.
    """
    n = len(sql)
    j = i + 1
    while j < n:
        c = sql[j]
        if escapes and c == "\\":
            j += 2
        elif c == "'":
            if j + 1 < n and sql[j + 1] == "'":
                j += 2
                continue
            siguiente = _continua_literal(sql, j + 1)
            if siguiente is None:
                return j + 1
            j = siguiente + 1
        else:
            j += 1
    return None


@dataclass(frozen=True)
class _Lexico:
    """Lo que :func:`_analizar` sabe del SQL tras un recorrido."""

    #: ``False`` si un literal, identificador o comentario de bloque no se cierra
    #: (lo que viene detrás no se analizó; Postgres lo rechazará igualmente).
    completo: bool
    #: Índice donde empieza la cola ``; …`` final (``;``, espacios y comentarios).
    corte: int | None
    #: Identificadores en posición de código, en minúsculas (los ``"…"`` sin comillas).
    nombres: tuple[str, ...]
    #: Hay algún identificador ``U&"…"`` (con escapes Unicode que no se descifran).
    unicode: bool


def _analizar(sql: str) -> _Lexico:
    """Un recorrido lineal con los estados léxicos de Postgres (``scan.l``).

    Reconoce cadenas ``'…'`` (``E'…'`` con ``\\``, ``''`` doblada y la
    continuación en otra línea), identificadores ``"…"`` y ``U&"…"``, cadenas
    entre dólares ``$tag$…$tag$``, parámetros ``$1``, números, comentarios
    ``-- …`` (hasta ``\\n`` o ``\\r``) y ``/* … */`` anidados. Así distingue un
    ``;`` o un nombre de función en código de uno que vive en un literal o un
    comentario. Coste lineal y sin retroceso.
    """
    n = len(sql)
    i = 0
    corte: int | None = None
    nombres: list[str] = []
    unicode = False

    def incompleto() -> _Lexico:
        return _Lexico(False, None, tuple(nombres), unicode)

    while i < n:
        c = sql[i]
        if c in _ESPACIOS:
            i += 1
        elif c == ";":
            if corte is None:
                corte = i
            i += 1
        elif sql.startswith("--", i):
            while i < n and sql[i] not in _SALTOS:
                i += 1
        elif sql.startswith("/*", i):
            profundidad = 1
            i += 2
            while i < n and profundidad:
                if sql.startswith("/*", i):
                    profundidad += 1
                    i += 2
                elif sql.startswith("*/", i):
                    profundidad -= 1
                    i += 2
                else:
                    i += 1
            if profundidad:
                return incompleto()
        else:
            corte = None
            if c in "eE" and sql.startswith("'", i + 1):
                fin = _fin_literal(sql, i + 1, escapes=True)
            elif c in "uU" and sql.startswith("&'", i + 1):
                fin = _fin_literal(sql, i + 2, escapes=False)
            elif c == "'":
                fin = _fin_literal(sql, i, escapes=False)
            elif c == '"' or (c in "uU" and sql.startswith('&"', i + 1)):
                if c != '"':
                    unicode = True
                    i += 2
                partes: list[str] = []
                j = i + 1
                while True:
                    k = sql.find('"', j)
                    if k < 0:
                        return incompleto()
                    partes.append(sql[j:k])
                    if sql.startswith('"', k + 1):  # ``""`` es una comilla del nombre
                        partes.append('"')
                        j = k + 2
                        continue
                    break
                nombres.append("".join(partes).lower())
                fin = k + 1
            elif _inicio_ident(c):
                j = i + 1
                while j < n and _es_ident(sql[j]):
                    j += 1
                nombres.append(sql[i:j].lower())
                fin = j
            elif "0" <= c <= "9" or (c == "." and i + 1 < n and "0" <= sql[i + 1] <= "9"):
                # Número: dígitos, ``.`` y ``_``; lo que siga (``e5``, ``x1F``,
                # ``abc``) se analiza como identificador aparte, que es lo prudente.
                j = i + 1
                while j < n and (("0" <= sql[j] <= "9") or sql[j] in "._"):
                    j += 1
                fin = j
            elif c == "$" and (tag := _etiqueta_dolar(sql, i)):
                k = sql.find(tag, i + len(tag))
                if k < 0:
                    return incompleto()
                fin = k + len(tag)
            elif c == "$":
                j = i + 1
                while j < n and "0" <= sql[j] <= "9":  # parámetro ``$1``
                    j += 1
                fin = j
            else:
                fin = i + 1
            if fin is None:
                return incompleto()
            i = fin
    return _Lexico(True, corte, tuple(nombres), unicode)


# ── Funciones vetadas ──────────────────────────────────────────────────────
#
# El rol es la frontera, pero hay funciones de ``pg_catalog`` que ``PUBLIC``
# puede ejecutar y que en Supabase no se pueden retirar sin romper a otros
# roles: los cerrojos de aviso son compartidos entre roles (con
# ``pg_advisory_lock`` el SQL del LLM bloquearía la cadena de ``audit_log`` o
# las familias OAuth), ``pg_notify`` y las señales llegan a otros procesos,
# ``pg_logical_emit_message`` escribe WAL aun en solo lectura, y
# ``query_to_xml``, ``ts_stat``, ``ts_rewrite`` o ``dblink`` ejecutan SQL
# escrito en texto, que este veto no vería. Es defensa en profundidad (ADR-036):
# el motor del riesgo es la inyección de instrucciones desde el texto de los
# pliegos, que el LLM lee y podría obedecer.

_VETADAS = frozenset(
    {
        "query_to_xml",
        "query_to_xmlschema",
        "query_to_xml_and_xmlschema",
        "cursor_to_xml",
        "cursor_to_xmlschema",
        "pg_notify",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "set_config",
        "ts_stat",
        "ts_rewrite",
        # Asignan un xid aunque la transacción sea de solo lectura: su commit
        # escribe WAL y consume identificadores de transacción.
        "pg_current_xact_id",
        "txid_current",
        "pg_drop_replication_slot",
    }
)
_VETADAS_PREFIJO = (
    "pg_advisory_",
    "pg_try_advisory_",
    "dblink",
    # ``pg_logical_emit_message`` escribe WAL en una transacción de solo lectura
    # (gigabytes en 15 s llenarían el disco); ``pg_logical_slot_*`` y las de
    # ranuras de replicación retendrían WAL. Hoy las ranuras las frena
    # ``NOREPLICATION``; se vetan igual.
    "pg_logical_",
    "pg_create_",
    "pg_copy_",
    "pg_replication_",
)
_PISTA_VETADA = (
    "En el MCP no se admiten cerrojos de aviso (pg_advisory_*), pg_notify, señales "
    "a otros procesos, set_config, las funciones que escriben WAL o asignan "
    "transacción (pg_logical_*, ranuras de replicación, pg_current_xact_id, "
    "txid_current) ni las que ejecutan SQL escrito en texto (query_to_xml, "
    "cursor_to_xml, ts_stat, ts_rewrite, dblink). Escribe la consulta directamente "
    "con SELECT."
)
_VETADA_EN_TEXTO = re.compile(
    "|".join([re.escape(v) for v in sorted(_VETADAS)] + [re.escape(p) for p in _VETADAS_PREFIJO]),
    re.IGNORECASE,
)


def _vetada(nombre: str) -> bool:
    return nombre in _VETADAS or nombre.startswith(_VETADAS_PREFIJO)


def _rechazar_vetadas(sql: str, lexico: _Lexico) -> None:
    """``ErrorConsulta`` si el SQL nombra en código una función vetada.

    Se compara el identificador (sin comillas y en minúsculas) haya o no un
    ``(`` detrás: entre el nombre y el paréntesis cabe un comentario. Si el
    recorrido no terminó (literal sin cerrar), se mira el texto entero: Postgres
    rechazará la sentencia, pero por si el léxico se quedara corto.
    """
    if lexico.unicode:
        raise ErrorConsulta(
            None,
            'Los identificadores U&"…" no se admiten en el MCP.',
            'Escribe el nombre tal cual, sin U&"…" ni escapes Unicode.',
        )
    for nombre in lexico.nombres:
        if _vetada(nombre):
            raise ErrorConsulta(
                None, f"La función {nombre} no está permitida en el MCP.", _PISTA_VETADA
            )
    if not lexico.completo and (hallada := _VETADA_EN_TEXTO.search(sql)):
        raise ErrorConsulta(
            None,
            f"La función {hallada.group(0).lower()} no está permitida en el MCP.",
            _PISTA_VETADA,
        )


def normalizar_sql(sql: str) -> str:
    """Quita espacios y la cola ``; …`` y veta funciones; rechaza lo vacío o largo.

    Las funciones vetadas (:data:`_VETADAS`) se rechazan aquí, antes de tocar la
    base, con ``ErrorConsulta(sqlstate=None)``.
    """
    if len(sql) > 2 * MAX_CHARS_SQL:  # tope barato antes de recorrer el texto
        raise ErrorConsulta(
            None,
            f"La consulta tiene {len(sql)} caracteres; el máximo es {MAX_CHARS_SQL}.",
            "Simplifica la consulta o divídela en varias.",
        )
    limpio = sql.strip()
    lexico = _analizar(limpio)
    if lexico.corte is not None:
        limpio = limpio[: lexico.corte].rstrip()
    if not limpio:
        raise ErrorConsulta(None, "La consulta está vacía.", None)
    if len(limpio) > MAX_CHARS_SQL:
        raise ErrorConsulta(
            None,
            f"La consulta tiene {len(limpio)} caracteres; el máximo es {MAX_CHARS_SQL}.",
            "Simplifica la consulta o divídela en varias.",
        )
    _rechazar_vetadas(limpio, lexico)
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
    ``uuid``, un ``numeric`` que no cabe en ``float`` y el resto de tipos sin
    representación JSON caen a texto.
    """
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, Decimal):
        if not v.is_finite():
            return None
        convertido = float(v)
        # Un ``numeric`` finito pero fuera del rango de ``float`` (``1e400``) da
        # ``inf``, que ``json.dumps`` escribiría como ``Infinity`` (JSON no válido):
        # se devuelve su texto.
        return convertido if math.isfinite(convertido) else _recortar(str(v))
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


#: Filas por ``FETCH`` del cursor de servidor de :func:`ejecutar_select`.
_FILAS_POR_LOTE = 50

_SQL_STATEMENT_TIMEOUT = (
    "SELECT setting::bigint FROM pg_catalog.pg_settings WHERE name = 'statement_timeout'"
)


def _error_de_tiempo() -> ErrorConsulta:
    return ErrorConsulta("57014", "canceling statement due to statement timeout", PISTAS["57014"])


def _leer_por_lotes(
    conn: psycopg.Connection[tuple[object, ...]], envuelta: str, max_filas: int
) -> tuple[list[str], list[list[JSONValue]]]:
    """Lee el resultado con un cursor de servidor, lote a lote, y para en cuanto sobra.

    ``fetchall`` traería hasta ``max_filas + 1`` filas enteras a memoria antes de
    recortar (``documentos.texto`` es el texto completo de un PDF). Aquí cada
    lote se serializa (celdas ya recortadas) y se deja de pedir en cuanto hay
    ``max_filas + 1`` filas o la respuesta ya pasa de ``MAX_CHARS_RESPUESTA``:
    :func:`_acotar_respuesta` quitará filas y marcará ``truncado`` igual que antes.

    Con cursor, ``statement_timeout`` vale por sentencia (el ``DECLARE`` y cada
    ``FETCH``); para que el tope del rol siga siendo de la consulta entera, antes
    de cada ``FETCH`` se le deja como ``statement_timeout`` local lo que queda.
    """
    inicio = time.monotonic()
    fila_tope = conn.execute(_SQL_STATEMENT_TIMEOUT).fetchone()
    tope_ms = int(str(fila_tope[0])) if fila_tope is not None else 0
    with conn.cursor(name="mcp_consulta") as cur:
        cur.execute(envuelta, (max_filas + 1,))
        columnas = [str(d.name) for d in (cur.description or [])]
        filas: list[list[JSONValue]] = []
        tamano = 0
        while len(filas) <= max_filas and tamano <= MAX_CHARS_RESPUESTA:
            if tope_ms > 0:
                queda_ms = tope_ms - int((time.monotonic() - inicio) * 1000)
                if queda_ms <= 0:
                    raise _error_de_tiempo()
                conn.execute("SELECT set_config('statement_timeout', %s, true)", (f"{queda_ms}ms",))
            lote = cur.fetchmany(min(_FILAS_POR_LOTE, max_filas + 1 - len(filas)))
            if not lote:
                break
            for cruda in lote:
                fila = [serializar_valor(v) for v in cruda]
                filas.append(fila)
                tamano += len(json.dumps(fila)) + 2
    return columnas, filas


def ejecutar_select(sql: str, *, max_filas: int = MAX_FILAS) -> ResultadoConsulta:
    """Ejecuta ``sql`` con el rol MCP y devuelve filas serializadas y acotadas.

    En una transacción de solo lectura (el pool es *autocommit*; al devolver la
    conexión, :func:`_reiniciar_sesion` hace ``RESET ALL`` igual) y con un cursor
    de servidor leído por lotes (:func:`_leer_por_lotes`).
    """
    url = mcp_database_url()
    if not url:
        raise ErrorConsulta(None, "MCP_DATABASE_URL no configurada", None)
    envuelta = envolver(normalizar_sql(sql), max_filas)
    pool = _get_pool(url)
    inicio = time.perf_counter()
    try:
        with pool.connection() as conn, conn.transaction():
            conn.execute("SET TRANSACTION READ ONLY")
            columnas, filas = _leer_por_lotes(conn, envuelta, max_filas)
    except psycopg.Error as exc:
        raise _traducir(exc) from None
    duracion_ms = int((time.perf_counter() - inicio) * 1000)
    truncado = len(filas) > max_filas
    return _acotar_respuesta(columnas, filas[:max_filas], truncado, duracion_ms)


# ── Introspección ──────────────────────────────────────────────────────────
#
# Para ``describir_esquema`` / ``describir_tabla``. Tres reglas:
#
# * El nombre de la tabla **siempre** viaja como parámetro enlazado y se
#   resuelve en el servidor con ``to_regclass(quote_ident(%s))``: honra el
#   ``search_path`` de la conexión igual que lo haría el SQL del LLM (en
#   producción ``pg_catalog, public``; en los tests, el schema de cada test) y
#   un nombre hostil no es más que un nombre que no existe. ``current_schema()``
#   no sirve de ancla: con ``search_path = pg_catalog, public`` devuelve
#   ``pg_catalog``.
# * Solo se listan columnas con ``SELECT`` para el rol
#   (``has_column_privilege``): lo que el catálogo oculta, aquí ni aparece.
# * Quien llama (``mcp_server/tools/esquema.py``) valida el nombre contra el
#   catálogo antes de llegar aquí; estas funciones no son la frontera, el rol sí.

_IDENT_SEGURO = re.compile(r"^[a-z_][a-z0-9_]*$")

_SQL_COLUMNAS = """
SELECT a.attname::text,
       format_type(a.atttypid, a.atttypmod),
       NOT a.attnotnull
  FROM pg_catalog.pg_attribute a
 WHERE a.attrelid = to_regclass(quote_ident(%s))
   AND a.attnum > 0
   AND NOT a.attisdropped
   AND has_column_privilege(a.attrelid, a.attnum, 'SELECT')
 ORDER BY a.attnum
"""

_SQL_CLAVES_FORANEAS = """
SELECT o.attname::text, d.relname::text, r.attname::text
  FROM pg_catalog.pg_constraint c
 CROSS JOIN LATERAL unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(origen, destino, orden)
  JOIN pg_catalog.pg_attribute o ON o.attrelid = c.conrelid AND o.attnum = k.origen
  JOIN pg_catalog.pg_attribute r ON r.attrelid = c.confrelid AND r.attnum = k.destino
  JOIN pg_catalog.pg_class d ON d.oid = c.confrelid
 WHERE c.contype = 'f'
   AND c.conrelid = to_regclass(quote_ident(%s))
 ORDER BY c.conname, k.orden
"""

_SQL_FILAS_APROXIMADAS = """
SELECT t.nombre, COALESCE(c.reltuples, 0)::bigint
  FROM unnest(%s::text[]) AS t(nombre)
  LEFT JOIN pg_catalog.pg_class c ON c.oid = to_regclass(quote_ident(t.nombre))
"""


def _leer(sql: str, params: Sequence[object]) -> list[tuple[object, ...]]:
    """Ejecuta una consulta de catálogo con el rol MCP y devuelve las filas crudas."""
    url = mcp_database_url()
    if not url:
        raise ErrorConsulta(None, "MCP_DATABASE_URL no configurada", None)
    pool = _get_pool(url)
    try:
        with pool.connection() as conn:
            return conn.execute(sql, params).fetchall()
    except psycopg.Error as exc:
        raise _traducir(exc) from None


def columnas_de(tabla: str) -> list[dict[str, str | bool]]:
    """Columnas legibles por el rol de ``tabla``: ``nombre``, ``tipo`` y ``nulo``."""
    return [
        {"nombre": str(n), "tipo": str(t), "nulo": bool(nulo)}
        for n, t, nulo in _leer(_SQL_COLUMNAS, (tabla,))
    ]


def claves_foraneas_de(tabla: str) -> list[dict[str, str]]:
    """Claves foráneas de ``tabla``: ``columna``, ``tabla_destino``, ``columna_destino``."""
    return [
        {"columna": str(c), "tabla_destino": str(d), "columna_destino": str(r)}
        for c, d, r in _leer(_SQL_CLAVES_FORANEAS, (tabla,))
    ]


def filas_aproximadas(tablas: Sequence[str]) -> dict[str, int]:
    """Filas estimadas (``pg_class.reltuples``); ``-1`` (sin ``ANALYZE``) o ausente → ``0``."""
    if not tablas:
        return {}
    filas = _leer(_SQL_FILAS_APROXIMADAS, (list(tablas),))
    return {str(n): max(int(str(v)), 0) for n, v in filas}


def ejemplo_de(tabla: str, columnas: Sequence[str], *, n: int = 3) -> ResultadoConsulta:
    """``SELECT <columnas> FROM <tabla> LIMIT n`` con los identificadores validados.

    Solo admite identificadores ``[a-z_][a-z0-9_]*`` (los del catálogo y de las
    columnas reales del esquema), que se citan con comillas dobles: ningún
    carácter de usuario llega al SQL. ``n`` es un entero fijado por el código.
    """
    if not columnas or not all(_IDENT_SEGURO.fullmatch(i) for i in (tabla, *columnas)):
        raise ErrorConsulta(None, "Identificador no válido para el ejemplo.", None)
    lista = ", ".join(f'"{c}"' for c in columnas)
    sql = f'SELECT {lista} FROM "{tabla}" LIMIT {int(n)}'
    return ejecutar_select(sql, max_filas=int(n))
