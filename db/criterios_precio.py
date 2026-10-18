"""Recálculo de ``es_precio`` y ``peso_precio_pct`` sobre las filas guardadas.

La regla que decide qué criterio de adjudicación es el precio cambió (ver
``scraper.codice_parser.criterio_es_precio``), y una fila solo se corrige sola
cuando el anuncio se vuelve a ingerir. Todo lo que la regla necesita ya está
en ``licitacion_criterios_adjudicacion`` (tipo, subtipo, descripción, peso,
padre y lote), así que el backfill recalcula sin volver a leer el feed.

Este módulo pone el SQL (ADR-022) y las garantías de escritura; la regla la
pone quien llama, como una función ``CriteriosDeLicitacion -> Recalculo``. Lo
orquesta ``scripts/backfill_criterio_precio.py``.

Por lotes de ``licitacion_id``, una transacción por lote:

1. Bloquea las filas de ``licitaciones`` del lote (``FOR NO KEY UPDATE`` con un
   ``lock_timeout`` corto). La ingesta reemplaza los criterios en la misma
   transacción en que escribe la licitación, así que con ese bloqueo un
   expediente no cambia entre que se lee y se reescribe; si una ingesta lo
   tiene cogido, el lote falla rápido y el script lo reintenta.
2. Reescribe ``es_precio`` solo donde difiere del recalculado.
3. Reescribe ``peso_precio_pct`` solo si las marcas nuevas lo cambian **y** la
   columna tiene hoy exactamente el valor que derivaban las marcas guardadas.
   Si no lo tiene, la columna no salió de estas filas (la escribió otra
   versión del anuncio, o el upsert la conservó con ``COALESCE``), y el
   backfill no tiene base para pisarla: cuenta la licitación como
   «desalineada» y la deja para la re-ingesta.

Es idempotente: tras un pase las marcas guardadas ya son las nuevas y el
recálculo no encuentra nada que cambiar.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from db.connection import connect, connect_read


@dataclass(frozen=True)
class CriterioGuardado:
    """Una fila de ``licitacion_criterios_adjudicacion``, lo que la regla lee."""

    id: int
    lote_numero: str | None
    padre_orden: int | None
    peso: float | None
    es_precio: bool
    tipo_codigo: str | None
    subtipo_codigo: str | None
    descripcion: str | None


@dataclass(frozen=True)
class CriteriosDeLicitacion:
    licitacion_id: str
    #: Valor actual de ``licitaciones.peso_precio_pct``.
    peso_precio_pct: float | None
    #: Todos sus criterios, de todos los ámbitos, en orden de documento.
    criterios: tuple[CriterioGuardado, ...]


@dataclass(frozen=True)
class Recalculo:
    """Lo que la regla nueva dice de una licitación."""

    #: ``id`` de criterio → ``es_precio`` nuevo, para todos sus criterios.
    es_precio: dict[int, bool]
    #: ``peso_precio_pct`` que derivan las marcas guardadas y las nuevas.
    peso_antes: float | None
    peso_despues: float | None


@dataclass(frozen=True)
class CambioLicitacion:
    licitacion_id: str
    criterios: int
    peso_antes: float | None
    peso_despues: float | None
    #: ``igual`` (las marcas nuevas no lo cambian), ``reescrito`` o
    #: ``desalineada`` (cambia, pero la columna no tenía ``peso_antes``).
    peso: Literal["igual", "reescrito", "desalineada"]


@dataclass(frozen=True)
class Lote:
    #: Último ``licitacion_id`` del lote; ``None`` cuando ya no quedan.
    hasta: str | None
    licitaciones: int
    criterios_reescritos: int
    pesos_reescritos: int
    desalineadas: int
    cambios: tuple[CambioLicitacion, ...] = field(default_factory=tuple)


_SQL_IDS_DEL_LOTE = (
    "SELECT DISTINCT licitacion_id FROM licitacion_criterios_adjudicacion "
    "WHERE licitacion_id > %s ORDER BY licitacion_id LIMIT %s"
)
_SQL_LICITACIONES = (
    "SELECT id_externo, peso_precio_pct FROM licitaciones "
    "WHERE id_externo = ANY(%s) ORDER BY id_externo"
)
_SQL_CRITERIOS = (
    "SELECT licitacion_id, id, lote_numero, padre_orden, peso, es_precio, "
    "tipo_codigo, subtipo_codigo, descripcion "
    "FROM licitacion_criterios_adjudicacion WHERE licitacion_id = ANY(%s) "
    "ORDER BY licitacion_id, lote_numero NULLS FIRST, orden"
)
_SQL_REESCRIBIR_ES_PRECIO = (
    "UPDATE licitacion_criterios_adjudicacion AS c SET es_precio = v.es_precio "
    "FROM unnest(%s::bigint[], %s::boolean[]) AS v(id, es_precio) "
    "WHERE c.id = v.id AND c.es_precio IS DISTINCT FROM v.es_precio"
)
_SQL_REESCRIBIR_PESO = (
    "UPDATE licitaciones AS l SET peso_precio_pct = v.peso "
    "FROM unnest(%s::text[], %s::float8[]) AS v(id_externo, peso) "
    "WHERE l.id_externo = v.id_externo"
)


def _mismo_peso(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, abs_tol=1e-6)


def _leer(c: Any, ids: list[str], *, bloquear: bool) -> list[CriteriosDeLicitacion]:
    sql = _SQL_LICITACIONES + (" FOR NO KEY UPDATE" if bloquear else "")
    pesos = {str(fila[0]): fila[1] for fila in c.execute(sql, (ids,)).fetchall()}
    por_licitacion: dict[str, list[CriterioGuardado]] = {i: [] for i in pesos}
    for fila in c.execute(_SQL_CRITERIOS, (ids,)).fetchall():
        por_licitacion[str(fila[0])].append(
            CriterioGuardado(
                id=int(fila[1]),
                lote_numero=fila[2],
                padre_orden=fila[3],
                peso=fila[4],
                es_precio=bool(fila[5]),
                tipo_codigo=fila[6],
                subtipo_codigo=fila[7],
                descripcion=fila[8],
            )
        )
    return [
        CriteriosDeLicitacion(licitacion_id=i, peso_precio_pct=pesos[i], criterios=tuple(crit))
        for i, crit in por_licitacion.items()
    ]


def recalcular_lote(
    desde: str,
    tamano: int,
    recalcular: Callable[[CriteriosDeLicitacion], Recalculo],
    *,
    escribir: bool,
    lock_timeout_ms: int = 2000,
    statement_timeout_ms: int = 60000,
) -> Lote:
    """Recalcula las ``tamano`` licitaciones con criterios siguientes a ``desde``.

    Con ``escribir=False`` no bloquea ni escribe nada (va por la conexión de
    lectura) y devuelve lo que un pase real reescribiría.
    """
    conexion = connect() if escribir else connect_read(statement_timeout_ms=statement_timeout_ms)
    with conexion as c:
        if escribir:
            c.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")
            c.execute(f"SET LOCAL statement_timeout = {int(statement_timeout_ms)}")
        ids = [str(fila[0]) for fila in c.execute(_SQL_IDS_DEL_LOTE, (desde, tamano)).fetchall()]
        if not ids:
            return Lote(
                hasta=None,
                licitaciones=0,
                criterios_reescritos=0,
                pesos_reescritos=0,
                desalineadas=0,
            )

        ids_criterio: list[int] = []
        marcas: list[bool] = []
        ids_peso: list[str] = []
        pesos: list[float | None] = []
        cambios: list[CambioLicitacion] = []
        desalineadas = 0
        for lic in _leer(c, ids, bloquear=escribir):
            recalculo = recalcular(lic)
            cambian = [
                (crit.id, recalculo.es_precio[crit.id])
                for crit in lic.criterios
                if recalculo.es_precio.get(crit.id, crit.es_precio) != crit.es_precio
            ]
            cambia_peso = not _mismo_peso(recalculo.peso_antes, recalculo.peso_despues)
            if not cambian and not cambia_peso:
                continue
            reescribe_peso = cambia_peso and _mismo_peso(lic.peso_precio_pct, recalculo.peso_antes)
            if cambia_peso and not reescribe_peso:
                desalineadas += 1
            if reescribe_peso:
                ids_peso.append(lic.licitacion_id)
                pesos.append(recalculo.peso_despues)
            for id_criterio, marca in cambian:
                ids_criterio.append(id_criterio)
                marcas.append(marca)
            cambios.append(
                CambioLicitacion(
                    licitacion_id=lic.licitacion_id,
                    criterios=len(cambian),
                    peso_antes=recalculo.peso_antes,
                    peso_despues=recalculo.peso_despues,
                    peso=(
                        "reescrito" if reescribe_peso else "desalineada" if cambia_peso else "igual"
                    ),
                )
            )

        if escribir and ids_criterio:
            c.execute(_SQL_REESCRIBIR_ES_PRECIO, (ids_criterio, marcas))
        if escribir and ids_peso:
            c.execute(_SQL_REESCRIBIR_PESO, (ids_peso, pesos))

    return Lote(
        hasta=ids[-1],
        licitaciones=len(ids),
        criterios_reescritos=len(ids_criterio),
        pesos_reescritos=len(ids_peso),
        desalineadas=desalineadas,
        cambios=tuple(cambios),
    )
