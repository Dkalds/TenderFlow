"""Columnas sombra tipadas de ``licitaciones`` (T2, «núcleo tipado»).

``v133`` añade cuatro columnas junto a las que hoy son ``text`` o ``real``:

============================  ==========================  =====================
Columna vieja                 Sombra                      Tipo
============================  ==========================  =====================
``fecha_publicacion`` (text)  ``fecha_publicacion_ts``    ``timestamptz``
``fecha_limite`` (text)       ``fecha_limite_ts``         ``timestamptz``
``importe`` (real)            ``importe_num``             ``numeric(14,2)``
``duracion_valor`` (real)     ``duracion_valor_num``      ``numeric``
============================  ==========================  =====================

Este módulo es el punto único de **cómo se traduce** una columna vieja a su
sombra, en sus dos formas:

* **Gemelas Python** (:func:`a_timestamptz`, :func:`a_importe_num`,
  :func:`a_duracion_num`) — las usa la escritura dual de ``db/upsert.py``, que
  traduce el valor **antes** de que Postgres lo meta en la columna vieja. Para
  el importe eso es lo que importa: la sombra recibe el ``float`` de Python
  intacto, no lo que queda de él tras pasar por ``real``.
* **Gemelas SQL** (:func:`ts_sql`, :func:`importe_num_sql`,
  :func:`duracion_num_sql`) — las usa el backfill por lotes, que sólo tiene la
  columna vieja para leer.

y del **backfill** y su **verificación**, por lotes de clave primaria para no
tocar centenares de miles de filas en una sola transacción mientras el scraper
escribe (la lección de ``limpiar_ml_proba_fuera_de_poblacion``, PR #274).

Las lecturas **no** están aquí: los fragmentos de lectura dual viven en
``db/sql_fragments.py`` y no cambian nada hasta que ``NUCLEO_TIPADO_LECTURA``
se active, que es un paso posterior a la verificación del backfill en
producción (``docs/runbooks/nucleo-tipado-ventana.md``).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from db.connection import connect, connect_read

#: Las cuatro columnas sombra, en el orden en que la escritura dual las añade al
#: ``INSERT``. Cada una con la columna vieja de la que se deriva.
COLUMNAS_SOMBRA: tuple[tuple[str, str], ...] = (
    ("fecha_publicacion_ts", "fecha_publicacion"),
    ("fecha_limite_ts", "fecha_limite"),
    ("importe_num", "importe"),
    ("duracion_valor_num", "duracion_valor"),
)

# ── Fechas ────────────────────────────────────────────────────────────────
# Mismas expresiones regulares, carácter a carácter, que la función SQL
# ``nucleo_iso_a_timestamptz`` de ``v133``. ``[0-9]`` y no ``\d``: en Python
# ``\d`` casa también dígitos no ASCII, y en Postgres no.
_RE_SOLO_FECHA = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_RE_FECHA_HORA = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{1,6})?)?"
    r"(Z|[+-][0-9]{2}(:?[0-9]{2})?)?$"
)
_RE_OFFSET = re.compile(r"(Z|[+-][0-9]{2}(:?[0-9]{2})?)$")


def a_timestamptz(valor: str | None) -> datetime | None:
    """Gemela Python de ``nucleo_iso_a_timestamptz`` (``v133``).

    Reglas, en este orden:

    1. Fecha sola (``2026-09-18``) → medianoche **UTC** de ese día. Es lo que
       hace que el año-mes de la sombra leído en UTC coincida con el prefijo
       del texto, y con él la componente temporal de la clave canónica.
    2. Fecha y hora con offset (``…T09:00:00+02:00``, ``…Z``) → el instante
       que dice el offset. Es el formato de ``shared.dates.to_iso_datetime``,
       que ya normaliza a UTC.
    3. Fecha y hora sin offset → se lee como UTC, por coherencia con la regla 1
       y con ``now_utc_iso``.
    4. Todo lo demás → ``None``. Incluye lo que casa con el patrón pero no es
       una fecha (``2026-02-30``), el año ``0000`` y la hora ``24``, que
       Postgres aceptaría y Python no: se rechazan en los dos lados.

    ``None`` en la sombra con texto no nulo en la vieja es exactamente una
    «fecha no ISO» en el sentido de ``scripts/audit_domain_truth.py``: la
    verificación del backfill las cuenta aparte.
    """
    if valor is None:
        return None
    if valor[:4] == "0000":
        return None
    try:
        if _RE_SOLO_FECHA.match(valor):
            d = date.fromisoformat(valor)
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
        if not _RE_FECHA_HORA.match(valor) or valor[11:13] == "24":
            return None
        texto = valor[:10] + "T" + valor[11:]
        offset = _RE_OFFSET.search(texto)
        if offset is None:
            texto += "+00:00"
        else:
            sufijo = offset.group(0)
            if sufijo == "Z":
                normalizado = "+00:00"
            else:
                digitos = sufijo[1:].replace(":", "")
                normalizado = f"{sufijo[0]}{digitos[:2]}:{digitos[2:] or '00'}"
            texto = texto[: offset.start()] + normalizado
        return datetime.fromisoformat(texto)
    except ValueError:
        return None


def ts_sql(columna: str) -> str:
    """Gemela SQL de :func:`a_timestamptz` sobre una columna de texto."""
    return f"nucleo_iso_a_timestamptz({columna})"


# ── Importe y duración ────────────────────────────────────────────────────
#: ``numeric(14,2)`` admite hasta 999.999.999.999,99. Un importe mayor no es un
#: contrato: es un error de parseo (unidades en céntimos, un NIF leído como
#: cifra). Se deja la sombra a ``NULL`` en vez de abortar el lote del upsert con
#: un ``numeric field overflow``, y la verificación lo cuenta aparte.
IMPORTE_NUM_TOPE = Decimal("1000000000000")
_CENTIMO = Decimal("0.01")

#: Cifras significativas con las que Postgres convierte ``float8`` a
#: ``numeric`` (``DBL_DIG``, ``float8_numeric`` en ``numeric.c``). La gemela
#: Python redondea igual para que las dos den el mismo ``numeric`` a partir del
#: mismo ``float``.
_CIFRAS_FLOAT8 = 15


def _decimal_de_float(valor: float) -> Decimal | None:
    if math.isnan(valor) or math.isinf(valor):
        return None
    try:
        return Decimal(f"{valor:.{_CIFRAS_FLOAT8}g}")
    except InvalidOperation:  # pragma: no cover - el formato de arriba siempre es válido
        return None


def a_importe_num(valor: float | None) -> Decimal | None:
    """Gemela Python de :func:`importe_num_sql`: céntimos exactos o ``None``.

    Redondeo a céntimo **alejándose de cero** en el empate (``ROUND_HALF_UP``
    de ``decimal``), que es como redondea ``numeric`` en Postgres.
    """
    if valor is None:
        return None
    exacto = _decimal_de_float(float(valor))
    if exacto is None:
        return None
    redondeado = exacto.quantize(_CENTIMO, rounding=ROUND_HALF_UP)
    if abs(redondeado) >= IMPORTE_NUM_TOPE:
        return None
    return redondeado


def a_duracion_num(valor: float | None) -> Decimal | None:
    """Gemela Python de :func:`duracion_num_sql`. Sin redondeo: no es dinero."""
    if valor is None:
        return None
    return _decimal_de_float(float(valor))


def importe_num_sql(columna: str = "importe") -> str:
    """Gemela SQL de :func:`a_importe_num` sobre la columna vieja.

    El doble cast (``real`` → ``double precision`` → ``numeric``) no es
    redundante: ``real`` a ``numeric`` directo sólo conserva **seis** cifras
    significativas (``FLT_DIG``), así que 1.234.567,875 saldría 1.234.570. Pasar
    por ``double precision`` conserva lo que el ``real`` guarda de verdad. Lo que
    el ``real`` ya perdió no se recupera: eso sólo lo trae la escritura dual en
    la siguiente reingesta.
    """
    f8 = f"CAST({columna} AS double precision)"
    redondeado = f"round(CAST({f8} AS numeric), 2)"
    return (
        f"CASE WHEN {columna} IS NULL OR {f8} IN ('NaN', 'Infinity', '-Infinity') THEN NULL "
        f"WHEN abs({redondeado}) >= {IMPORTE_NUM_TOPE} THEN NULL "
        f"ELSE {redondeado} END"
    )


def duracion_num_sql(columna: str = "duracion_valor") -> str:
    """Gemela SQL de :func:`a_duracion_num` sobre la columna vieja."""
    f8 = f"CAST({columna} AS double precision)"
    return (
        f"CASE WHEN {columna} IS NULL OR {f8} IN ('NaN', 'Infinity', '-Infinity') THEN NULL "
        f"ELSE CAST({f8} AS numeric) END"
    )


def valores_sombra(data: dict[str, Any]) -> list[Any]:
    """Valores de las cuatro sombras para una fila del upsert, en orden.

    ``data`` es el ``asdict`` de la ``Licitacion`` **después** de las
    correcciones del upsert (la ``fecha_publicacion`` más temprana), para que
    cada sombra describa exactamente lo que se escribe en su columna vieja.
    """
    return [
        a_timestamptz(data.get("fecha_publicacion")),
        a_timestamptz(data.get("fecha_limite")),
        a_importe_num(data.get("importe")),
        a_duracion_num(data.get("duracion_valor")),
    ]


# ── Divergencia: cuándo una sombra no describe su columna vieja ───────────
#: Tolerancia relativa con la que una sombra numérica «describe» su columna
#: vieja. Es ``shared.numeric.FLOAT_REL_TOL`` y por el mismo motivo: en
#: producción la columna vieja es ``real``, y un ``importe_num`` escrito por la
#: escritura dual desde el ``float`` intacto **no** coincide con lo que se lee
#: del ``real``. Sin tolerancia, el backfill lo daría por divergente y lo
#: machacaría con el valor degradado — deshaciendo justo lo que la sombra
#: existe para arreglar. No se importa de ``shared.numeric`` porque esto es SQL
#: congelado en el sentido del backlog: bajar ``FLOAT_REL_TOL`` allí no debe
#: aflojar esta comprobación sin que nadie lo decida aquí.
_TOL_REL = "0.00001"


def _diverge_numerica_sql(sombra: str, conversion: str, tol_abs: str) -> str:
    return (
        f"(CASE WHEN ({conversion}) IS NULL THEN {sombra} IS NOT NULL "
        f"WHEN {sombra} IS NULL THEN TRUE "
        f"ELSE abs({sombra} - ({conversion})) > "
        f"greatest({tol_abs}, abs({conversion}) * {_TOL_REL}) END)"
    )


def _divergencias_sql() -> dict[str, str]:
    """Predicado «esta sombra no describe su columna vieja», por sombra."""
    return {
        "fecha_publicacion_ts": (
            f"(fecha_publicacion_ts IS DISTINCT FROM {ts_sql('fecha_publicacion')})"
        ),
        "fecha_limite_ts": f"(fecha_limite_ts IS DISTINCT FROM {ts_sql('fecha_limite')})",
        "importe_num": _diverge_numerica_sql("importe_num", importe_num_sql(), "0.01"),
        "duracion_valor_num": _diverge_numerica_sql(
            "duracion_valor_num", duracion_num_sql(), "0.000000001"
        ),
    }


# ── Backfill por lotes ────────────────────────────────────────────────────
@dataclass(frozen=True)
class Lote:
    """Resultado de un lote del backfill o de la verificación."""

    #: Última ``id_externo`` del lote: el cursor del siguiente. ``None`` si el
    #: lote salió vacío, o sea, si ya no quedan filas.
    hasta: str | None
    filas: int
    #: Filas con al menos una sombra divergente (verificación) o filas
    #: reescritas (backfill).
    afectadas: int
    detalle: dict[str, int]


_SQL_FIN_DE_LOTE = (
    "SELECT max(id_externo), count(*) FROM ("
    "SELECT id_externo FROM licitaciones WHERE id_externo > %s "
    "ORDER BY id_externo LIMIT %s) s"
)


def _fin_de_lote(c: Any, desde: str, tamano: int) -> tuple[str | None, int]:
    """Última clave y número de filas del lote que empieza después de ``desde``."""
    fila = c.execute(_SQL_FIN_DE_LOTE, (desde, tamano)).fetchone()
    if fila is None or fila[0] is None:
        return None, 0
    return str(fila[0]), int(fila[1])


def _sql_rellenar() -> str:
    div = _divergencias_sql()
    asignaciones = ", ".join(
        f"{sombra} = CASE WHEN {div[sombra]} THEN {conversion} ELSE {sombra} END"
        for sombra, conversion in (
            ("fecha_publicacion_ts", ts_sql("fecha_publicacion")),
            ("fecha_limite_ts", ts_sql("fecha_limite")),
            ("importe_num", importe_num_sql()),
            ("duracion_valor_num", duracion_num_sql()),
        )
    )
    alguna = " OR ".join(div.values())
    return (
        f"UPDATE licitaciones SET {asignaciones} "
        "WHERE id_externo > %s AND id_externo <= %s "
        f"AND ({alguna})"
    )


def rellenar_lote(
    desde: str,
    tamano: int,
    *,
    lock_timeout_ms: int = 2000,
    statement_timeout_ms: int = 60000,
) -> Lote:
    """Rellena las sombras de las ``tamano`` filas siguientes a ``desde``.

    Una transacción por lote. Sólo reescribe las filas cuya sombra **diverge**
    de su columna vieja, así que es idempotente y reanudable: repetirlo sobre
    un rango ya rellenado no escribe nada, y una fila que otro escritor tocó
    después del primer pase (``scripts/fix_dates_adjudicaciones.py``, un
    ``UPDATE`` a mano) se corrige en el siguiente.

    ``lock_timeout`` corto a propósito: si el lote choca con los locks de fila
    de una ingesta en curso, falla en dos segundos y el script lo reintenta, en
    vez de hacer esperar a la ingesta detrás del backfill.
    """
    with connect() as c:
        c.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")
        c.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
        hasta, filas = _fin_de_lote(c, desde, tamano)
        if hasta is None:
            return Lote(hasta=None, filas=0, afectadas=0, detalle={})
        c.execute(_sql_rellenar(), (desde, hasta))
        afectadas = max(c.rowcount, 0)
    return Lote(hasta=hasta, filas=filas, afectadas=afectadas, detalle={})


def _sql_verificar() -> str:
    div = _divergencias_sql()
    columnas = ", ".join(
        f"count(*) FILTER (WHERE {pred}) AS {sombra}" for sombra, pred in div.items()
    )
    alguna = " OR ".join(div.values())
    return (
        "SELECT count(*) AS filas, "
        f"count(*) FILTER (WHERE {alguna}) AS divergentes, "
        f"{columnas}, "
        # «Fechas no ISO»: texto presente y sombra imposible. No son
        # divergencia —la sombra describe bien que no hay fecha—, pero son las
        # filas que impedirían retirar la columna de texto sin perder nada.
        "count(*) FILTER (WHERE fecha_publicacion IS NOT NULL "
        "AND fecha_publicacion_ts IS NULL) AS fecha_publicacion_no_iso, "
        "count(*) FILTER (WHERE fecha_limite IS NOT NULL "
        "AND fecha_limite_ts IS NULL) AS fecha_limite_no_iso, "
        "count(*) FILTER (WHERE importe IS NOT NULL "
        "AND importe_num IS NULL) AS importe_sin_sombra, "
        # La clave canónica toma el año-mes del TEXTO (`periodo_publicacion_sql`).
        # Esto cuenta las filas en las que leerlo de la sombra en UTC daría otro
        # mes: un offset distinto de UTC que cruza medianoche a fin de mes. Si
        # no es cero, la clave NO puede pasar a leer la sombra sin moverse.
        "count(*) FILTER (WHERE fecha_publicacion_ts IS NOT NULL "
        "AND to_char(fecha_publicacion_ts AT TIME ZONE 'UTC', 'YYYY-MM') "
        "<> substr(fecha_publicacion, 1, 7)) AS periodo_distinto "
        "FROM licitaciones WHERE id_externo > %s AND id_externo <= %s"
    )


#: Columnas del detalle de la verificación, en el orden del ``SELECT``.
DETALLE_VERIFICACION: tuple[str, ...] = (
    *(sombra for sombra, _ in COLUMNAS_SOMBRA),
    "fecha_publicacion_no_iso",
    "fecha_limite_no_iso",
    "importe_sin_sombra",
    "periodo_distinto",
)


def verificar_lote(desde: str, tamano: int, *, statement_timeout_ms: int = 60000) -> Lote:
    """Cuenta, sin escribir, cuánto se aparta cada sombra en el lote siguiente.

    Por lotes igual que el backfill: un ``count`` sobre la tabla entera es un
    seq scan de 1,3 M filas que cruza el ``statement_timeout`` del rol.
    """
    with connect_read() as c:
        c.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
        hasta, _ = _fin_de_lote(c, desde, tamano)
        if hasta is None:
            return Lote(hasta=None, filas=0, afectadas=0, detalle={})
        fila = c.execute(_sql_verificar(), (desde, hasta)).fetchone()
    filas, divergentes, *resto = (int(v or 0) for v in fila)
    return Lote(
        hasta=hasta,
        filas=filas,
        afectadas=divergentes,
        detalle=dict(zip(DETALLE_VERIFICACION, resto, strict=True)),
    )


# `pg_attribute` y no `information_schema.columns`: la vista del estándar
# evalúa privilegios columna a columna sobre todo el catálogo antes de filtrar,
# y esta consulta corre en cada chunk del upsert. `to_regclass` resuelve la
# tabla por el search_path, igual que el `INSERT` que viene después.
_SQL_COLUMNAS_SOMBRA = (
    "SELECT count(*) FROM pg_catalog.pg_attribute "
    "WHERE attrelid = to_regclass('licitaciones') "
    "AND attnum > 0 AND NOT attisdropped AND attname = ANY(%s)"
)


def sombras_disponibles(c: Any) -> bool:
    """``True`` si las cuatro columnas de ``v133`` existen en ``licitaciones``.

    La escritura dual depende de esto y no de un flag: el código puede llegar a
    producción antes que la migración —producción ha llegado a ir quince
    revisiones por detrás— y un ``INSERT`` con columnas que no existen tumbaría
    toda la ingesta.
    """
    fila = c.execute(_SQL_COLUMNAS_SOMBRA, ([s for s, _ in COLUMNAS_SOMBRA],)).fetchone()
    return fila is not None and int(fila[0]) == len(COLUMNAS_SOMBRA)
