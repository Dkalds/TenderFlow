"""Sombras ``<columna>_ts timestamptz`` de las fechas en texto (``v159``).

Fase 1 del ítem «Pasar las fechas de ``text`` a ``timestamptz``» del backlog.
Es la misma receta que el núcleo tipado (``db/nucleo_tipado.py``, ``v133``)
extendida a catorce fechas más: la columna de texto se queda tal cual y al lado
nace su sombra tipada, que se rellena sin bloquear y se lee solo cuando el
relleno está verificado.

Este módulo es el punto único de:

* **qué** columnas tienen sombra (:data:`TABLAS`, gemelo del ``COLUMNAS``
  congelado de la migración);
* **cómo** se traduce el texto (:func:`a_timestamptz`, reexportada de
  ``db.nucleo_tipado``: una sola regla para todas las sombras de fecha, con su
  gemela SQL ``nucleo_iso_a_timestamptz``);
* la **escritura dual** de ``licitaciones`` (:func:`valores_lic`,
  :func:`sombras_presentes`), que usa ``db/upsert.py``. Las demás tablas no la
  necesitan: sus sombras las mantiene un trigger de ``v159``;
* el **backfill** y su **verificación**, por lotes de clave primaria
  (:func:`rellenar_lote`, :func:`verificar_lote`), que orquesta
  ``scripts/backfill_fechas_ts.py``.

Las lecturas duales viven en ``db/sql_fragments.py`` (:func:`instante_sql`) y no
cambian nada hasta que se enciende ``FECHAS_TS_LECTURA``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from db.connection import connect, connect_read
from db.nucleo_tipado import a_timestamptz, ts_sql

__all__ = [
    "LIC_COLUMNAS_UPSERT",
    "TABLAS",
    "Lote",
    "TablaFechas",
    "a_timestamptz",
    "cursor_de_texto",
    "cursor_inicial",
    "detalle_verificacion",
    "rellenar_lote",
    "sombra",
    "sombras_presentes",
    "sql_rellenar",
    "sql_verificar",
    "tabla",
    "valores_lic",
    "verificar_lote",
]


def sombra(columna: str) -> str:
    """Nombre de la sombra de ``columna``: siempre ``<columna>_ts``."""
    return f"{columna}_ts"


@dataclass(frozen=True)
class TablaFechas:
    """Una tabla con fechas en texto y sus sombras."""

    nombre: str
    #: Clave primaria por la que el backfill recorre la tabla en lotes.
    pk: str
    pk_entera: bool
    columnas: tuple[str, ...]
    #: Quién mantiene la sombra en cada escritura.
    escritura: Literal["upsert", "trigger"]
    #: ``False`` si el script no puede reescribirla: ``pursuit_events`` es
    #: append-only (trigger de ``v61``) y la rellena ``v159`` entera, que es
    #: diminuta. Verificarla sí se puede.
    backfill: bool = True

    @property
    def pares(self) -> tuple[tuple[str, str], ...]:
        """``(sombra, columna)`` en el orden de :attr:`columnas`."""
        return tuple((sombra(c), c) for c in self.columnas)


TABLAS: tuple[TablaFechas, ...] = (
    TablaFechas(
        "licitaciones",
        "id_externo",
        False,
        (
            "fecha_extraccion",
            "primera_extraccion",
            "fecha_inicio",
            "fecha_fin",
            "fecha_actualizacion_fuente",
        ),
        "upsert",
    ),
    TablaFechas("adjudicaciones", "id", True, ("fecha_adjudicacion",), "trigger"),
    TablaFechas("licitaciones_history", "id", True, ("captured_at",), "trigger"),
    TablaFechas("documentos", "id", True, ("created_at", "fetched_at", "updated_at"), "trigger"),
    TablaFechas("pursuit_events", "id", True, ("created_at",), "trigger", backfill=False),
    TablaFechas("user_notifications", "id", True, ("created_at", "read_at"), "trigger"),
)

_POR_NOMBRE: dict[str, TablaFechas] = {t.nombre: t for t in TABLAS}


def tabla(nombre: str) -> TablaFechas:
    """La :class:`TablaFechas` de ``nombre``; ``KeyError`` si no tiene sombras."""
    return _POR_NOMBRE[nombre]


# ── Escritura dual de licitaciones ───────────────────────────────────────
#: Las columnas de ``licitaciones`` cuya sombra escribe ``db/upsert.py``: las
#: que el upsert escribe. ``primera_extraccion`` no está en el dataclass
#: ``Licitacion`` (ver ``_LIC_INSERT_ONLY_FIELDS`` en ``db/upsert.py``), así que
#: su sombra solo la rellena el backfill; cuando el upsert la escriba, entra
#: aquí.
LIC_COLUMNAS_UPSERT: tuple[str, ...] = (
    "fecha_extraccion",
    "fecha_inicio",
    "fecha_fin",
    "fecha_actualizacion_fuente",
)


def valores_lic(data: dict[str, Any]) -> list[datetime | None]:
    """Sombras de :data:`LIC_COLUMNAS_UPSERT` para una fila del upsert, en orden."""
    return [a_timestamptz(data.get(col)) for col in LIC_COLUMNAS_UPSERT]


# `pg_attribute` y no `information_schema.columns`, por lo mismo que
# `db.nucleo_tipado.sombras_disponibles`: corre en cada chunk del upsert.
_SQL_COLUMNAS_PRESENTES = (
    "SELECT count(*) FROM pg_catalog.pg_attribute "
    "WHERE attrelid = to_regclass(%s) "
    "AND attnum > 0 AND NOT attisdropped AND attname = ANY(%s)"
)


def sombras_presentes(c: Any, nombre_tabla: str, columnas: tuple[str, ...]) -> bool:
    """``True`` si existen las sombras de todas ``columnas`` en ``nombre_tabla``.

    La escritura dual depende de esto y no de un flag: el código puede llegar a
    producción antes que ``v159``, y un ``INSERT`` con columnas inexistentes
    tumbaría la ingesta entera.
    """
    nombres = [sombra(col) for col in columnas]
    fila = c.execute(_SQL_COLUMNAS_PRESENTES, (nombre_tabla, nombres)).fetchone()
    return fila is not None and int(fila[0]) == len(nombres)


# ── Backfill y verificación por lotes ────────────────────────────────────
@dataclass(frozen=True)
class Lote:
    """Resultado de un lote del backfill o de la verificación."""

    #: Última clave del lote: el cursor del siguiente. ``None`` si el lote salió
    #: vacío, o sea, si ya no quedan filas.
    hasta: str | int | None
    filas: int
    #: Filas reescritas (backfill) o con alguna sombra divergente (verificación).
    afectadas: int
    detalle: dict[str, int]


def cursor_inicial(t: TablaFechas) -> str | int:
    """Cota exclusiva por debajo de cualquier clave de ``t``."""
    return -(2**63) if t.pk_entera else ""


def cursor_de_texto(t: TablaFechas, valor: str) -> str | int:
    """Traduce el ``--desde`` de la línea de órdenes al tipo de la clave."""
    if not valor:
        return cursor_inicial(t)
    return int(valor) if t.pk_entera else valor


def _divergente(sombra_col: str, columna: str) -> str:
    return f"({sombra_col} IS DISTINCT FROM {ts_sql(columna)})"


def _sql_fin_de_lote(t: TablaFechas) -> str:
    # Identificadores de `TABLAS` (código), nunca de entrada externa.
    return (
        f"SELECT max({t.pk}), count(*) FROM ("
        f"SELECT {t.pk} FROM {t.nombre} WHERE {t.pk} > %s ORDER BY {t.pk} LIMIT %s) s"
    )


def _fin_de_lote(c: Any, t: TablaFechas, desde: str | int, tamano: int) -> tuple[Any, int]:
    fila = c.execute(_sql_fin_de_lote(t), (desde, tamano)).fetchone()
    if fila is None or fila[0] is None:
        return None, 0
    return fila[0], int(fila[1])


def sql_rellenar(t: TablaFechas) -> str:
    """``UPDATE`` de un rango de claves que solo toca las filas divergentes.

    Solo asigna las sombras, nunca la columna de texto: los triggers de ``v159``
    son ``UPDATE OF <texto>`` y no se disparan, así que el backfill no recalcula
    dos veces ni cambia nada que un lector de texto vea.
    """
    asignaciones = ", ".join(
        f"{s} = CASE WHEN {_divergente(s, c)} THEN {ts_sql(c)} ELSE {s} END" for s, c in t.pares
    )
    alguna = " OR ".join(_divergente(s, c) for s, c in t.pares)
    return f"UPDATE {t.nombre} SET {asignaciones} WHERE {t.pk} > %s AND {t.pk} <= %s AND ({alguna})"


def rellenar_lote(
    nombre_tabla: str,
    desde: str | int,
    tamano: int,
    *,
    lock_timeout_ms: int = 2000,
    statement_timeout_ms: int = 60000,
) -> Lote:
    """Rellena las sombras de las ``tamano`` filas siguientes a ``desde``.

    Una transacción por lote. Idempotente y reanudable: solo reescribe filas
    cuya sombra **diverge** de su texto, así que repetir un rango ya rellenado
    no escribe nada, y una fila que otro escritor tocó entre medias (un
    ``UPDATE`` de ``licitaciones`` fuera del upsert) se corrige en el siguiente
    pase. ``lock_timeout`` corto: si choca con una ingesta, falla en dos
    segundos y el script reintenta, en vez de hacer esperar a la ingesta.
    """
    t = tabla(nombre_tabla)
    with connect() as c:
        c.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")
        c.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
        hasta, filas = _fin_de_lote(c, t, desde, tamano)
        if hasta is None:
            return Lote(hasta=None, filas=0, afectadas=0, detalle={})
        c.execute(sql_rellenar(t), (desde, hasta))
        afectadas = max(c.rowcount, 0)
    return Lote(hasta=hasta, filas=filas, afectadas=afectadas, detalle={})


def detalle_verificacion(t: TablaFechas) -> tuple[str, ...]:
    """Claves del detalle de :func:`verificar_lote`, en el orden del ``SELECT``."""
    return (*(s for s, _ in t.pares), *(f"{c}_no_iso" for c in t.columnas))


def sql_verificar(t: TablaFechas) -> str:
    """Cuenta, por sombra, las filas divergentes y las «no ISO» del rango.

    «No ISO» es texto presente con sombra ``NULL``: la sombra describe bien que
    no hay fecha legible, así que no es divergencia, pero son justo las filas
    que impedirían retirar la columna de texto (fase 2) sin perder nada.
    """
    divergencias = ", ".join(
        f"count(*) FILTER (WHERE {_divergente(s, c)}) AS {s}" for s, c in t.pares
    )
    no_iso = ", ".join(
        f"count(*) FILTER (WHERE {c} IS NOT NULL AND {s} IS NULL) AS {c}_no_iso" for s, c in t.pares
    )
    alguna = " OR ".join(_divergente(s, c) for s, c in t.pares)
    return (
        f"SELECT count(*), count(*) FILTER (WHERE {alguna}), "
        f"{divergencias}, {no_iso} "
        f"FROM {t.nombre} WHERE {t.pk} > %s AND {t.pk} <= %s"
    )


def verificar_lote(
    nombre_tabla: str, desde: str | int, tamano: int, *, statement_timeout_ms: int = 60000
) -> Lote:
    """Cuenta, sin escribir, cuánto se aparta cada sombra en el lote siguiente."""
    t = tabla(nombre_tabla)
    with connect_read() as c:
        c.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
        hasta, _ = _fin_de_lote(c, t, desde, tamano)
        if hasta is None:
            return Lote(hasta=None, filas=0, afectadas=0, detalle={})
        fila = c.execute(sql_verificar(t), (desde, hasta)).fetchone()
    filas, divergentes, *resto = (int(v or 0) for v in fila)
    return Lote(
        hasta=hasta,
        filas=filas,
        afectadas=divergentes,
        detalle=dict(zip(detalle_verificacion(t), resto, strict=True)),
    )
