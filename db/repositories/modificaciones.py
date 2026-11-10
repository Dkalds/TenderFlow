"""Modificaciones de contrato publicadas (art. 207.3 LCSP), tabla ``contrato_modificaciones``.

La escriben los conectores: PLACSP desde el bloque ``cac:ContractModification``
de cada entry, ya con su expediente; TED desde cada aviso ``can-modif``, sin
expediente hasta que :mod:`services.modificaciones` lo enlaza. El esquema lo
crea ``v180``. Qué contrato es cuál, qué importe es el final y cuándo hay
muestra para hablar de un órgano lo decide ``services/modificaciones.py``.

Escritura idempotente (AGENTS.md §3.2): upsert por ``clave``, que identifica la
modificación en su fuente (``placsp:…#<contrato>#<n>`` o ``ted:<aviso>``).
Reingerir actualiza la fila; no la duplica ni deshace un enlace ya hecho.

No es ``contrato_eventos``: aquellos son diferencias entre dos capturas de la
misma fila, y estas son lo que el órgano publicó como modificación.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, TypedDict

from db.database import connect, connect_read, now_utc_iso
from db.repositories.base import rows_to_dicts, typed_rows
from db.sql_fragments import organo_normalizado_sql

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "FilaAdjudicado",
    "FilaModificacion",
    "FilaModificacionDeOrgano",
    "FilaSinEnlazar",
    "ModificacionContrato",
    "adjudicado_por_lote",
    "de_licitacion",
    "del_organo_de",
    "enlazar",
    "expedientes_de_avisos",
    "expedientes_de_avisos_previos",
    "reemplazar_de_expedientes",
    "sin_enlazar",
    "upsert",
]


@dataclass
class ModificacionContrato:
    """Una modificación tal como la publica su fuente.

    Cada importe va con su base (ADR-032): ``sin_iva``, ``con_iva`` o
    ``desconocido``; ``None`` en la base solo cuando el importe falta.
    """

    clave: str
    fuente: str
    licitacion_id: str | None = None
    #: Cómo se llegó al expediente: ``fuente`` (la entry de PLACSP es el
    #: expediente), ``aviso_original`` (BT-1501), ``referencia`` (``idEvl`` o
    #: BT-22 dentro del mismo órgano). ``None`` mientras no se enlace.
    enlace: str | None = None
    numero: str | None = None
    contrato_ref: str | None = None
    lote_numero: str | None = None
    fecha_publicacion: str | None = None
    motivo_codigo: str | None = None
    motivo: str | None = None
    descripcion: str | None = None
    importe_modificacion: float | None = None
    importe_modificacion_base: str | None = None
    importe_final: float | None = None
    importe_final_base: str | None = None
    #: BT-720 de un aviso de TED: «valor publicado en el aviso», sin decir si es
    #: anterior o posterior a la modificación ni su base (ver ``v180``).
    importe_aviso: float | None = None
    importe_aviso_base: str | None = None
    moneda: str | None = None
    plazo_modificacion: float | None = None
    plazo_final: float | None = None
    plazo_unidad: str | None = None
    #: ``notice-identifier`` (UUID) del propio aviso de TED.
    identificador_aviso: str | None = None
    #: BT-1501 tal como lo publica TED: el número del aviso (``123-2025``) o su
    #: UUID con versión (``…-01``).
    aviso_original: str | None = None
    expediente_ref: str | None = None
    organo: str | None = None
    url: str | None = None
    fecha_extraccion: str = field(default_factory=now_utc_iso)


_COLUMNAS: tuple[str, ...] = tuple(ModificacionContrato.__dataclass_fields__)
# Tipos explícitos: dentro de un `VALUES` de subconsulta Postgres no hereda el
# tipo de la columna de destino, y un `NULL` sin tipo se lee como `text`.
_TIPOS: dict[str, str] = {
    "importe_modificacion": "double precision",
    "importe_final": "double precision",
    "importe_aviso": "double precision",
    "plazo_modificacion": "double precision",
    "plazo_final": "double precision",
}
_FILA = "(" + ", ".join(f"%s::{_TIPOS.get(c, 'text')}" for c in _COLUMNAS) + ")"
# El enlace no se deshace al reingerir: TED vuelve a traer el aviso sin
# expediente cada pasada de su ventana, y ya estaba enlazado.
_ACTUALIZAR = ", ".join(
    f"{c} = COALESCE(EXCLUDED.{c}, contrato_modificaciones.{c})"
    if c in ("licitacion_id", "enlace")
    else f"{c} = EXCLUDED.{c}"
    for c in _COLUMNAS
    if c != "clave"
)
_POR_SENTENCIA = 500


def upsert(items: Sequence[ModificacionContrato]) -> int:
    """Escribe las modificaciones (upsert por ``clave``). Devuelve cuántas filas tocó.

    Una modificación cuyo expediente no está en ``licitaciones`` se escribe sin
    él: la clave ajena no puede tumbar el lote, y la fila de PLACSP siempre se
    escribe antes en el mismo flush, así que solo pasa si esa escritura la
    descartó. Si la misma clave llega dos veces, gana la última.
    """
    ultimas = {m.clave: m for m in items}
    if not ultimas:
        return 0
    filas = list(ultimas.values())
    tocadas = 0
    cols = ", ".join(_COLUMNAS)
    proyeccion = ", ".join(
        {
            "licitacion_id": "l.id_externo",
            "enlace": "CASE WHEN l.id_externo IS NULL THEN NULL ELSE v.enlace END",
        }.get(col, f"v.{col}")
        for col in _COLUMNAS
    )
    with connect() as c:
        for inicio in range(0, len(filas), _POR_SENTENCIA):
            tanda = filas[inicio : inicio + _POR_SENTENCIA]
            valores: list[object] = []
            for m in tanda:
                datos = asdict(m)
                valores.extend(datos[k] for k in _COLUMNAS)
            sql = (
                f"INSERT INTO contrato_modificaciones ({cols}) "
                f"SELECT {proyeccion} "
                f"FROM (VALUES {', '.join(_FILA for _ in tanda)}) AS v({cols}) "
                "LEFT JOIN licitaciones l ON l.id_externo = v.licitacion_id "
                f"ON CONFLICT (clave) DO UPDATE SET {_ACTUALIZAR}"
            )
            tocadas += c.execute(sql, valores).rowcount or 0
    return tocadas


def reemplazar_de_expedientes(por_licitacion: dict[str, list[ModificacionContrato]]) -> int:
    """Deja las modificaciones de PLACSP de cada expediente como las trae su entry.

    La entry es una foto completa y acumulativa del expediente, y el ``cbc:ID``
    de una modificación no es estable: el 2,3 % de las claves cambiaron de
    contenido entre versiones en el ZIP 2026-10 (el ordinal se reutiliza para
    otra modificación). Por eso, además del upsert, se borran las de la fuente
    que la foto nueva ya no trae. Solo de los expedientes que llegan con alguna:
    una entry sin bloques no borra nada, porque los conectores que no leen el
    bloque (consultas, menores) también escriben expedientes ``placsp:``.
    """
    con_alguna = {lic: ms for lic, ms in por_licitacion.items() if ms}
    if not con_alguna:
        return 0
    claves = [m.clave for ms in con_alguna.values() for m in ms]
    with connect() as c:
        c.execute(
            "DELETE FROM contrato_modificaciones "
            "WHERE fuente = 'placsp' AND licitacion_id = ANY(%s) AND NOT (clave = ANY(%s))",
            (list(con_alguna), claves),
        )
    return upsert([m for ms in con_alguna.values() for m in ms])


class FilaSinEnlazar(TypedDict):
    """Un aviso de modificación aún sin expediente, con lo que sirve para buscarlo."""

    clave: str
    aviso_original: str | None
    expediente_ref: str | None
    organo: str | None
    url: str | None


def sin_enlazar(*, fuente: str, limite: int) -> list[FilaSinEnlazar]:
    """Las modificaciones de ``fuente`` sin expediente, de la más reciente a la más antigua."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT clave, aviso_original, expediente_ref, organo, url "
            "FROM contrato_modificaciones "
            "WHERE fuente = %s AND licitacion_id IS NULL "
            "ORDER BY fecha_publicacion DESC NULLS LAST, clave LIMIT %s",
            (fuente, limite),
        )
        return typed_rows(FilaSinEnlazar, rows_to_dicts(cur))


def enlazar(enlaces: Sequence[tuple[str, str, str]]) -> int:
    """Pone el expediente a cada ``(clave, licitacion_id, enlace)``. No pisa un enlace previo."""
    if not enlaces:
        return 0
    with connect() as c:
        cur = c.execute(
            "UPDATE contrato_modificaciones m SET licitacion_id = e.lic, enlace = e.enlace "
            "FROM unnest(%s::text[], %s::text[], %s::text[]) AS e(clave, lic, enlace) "
            "JOIN licitaciones l ON l.id_externo = e.lic "
            "WHERE m.clave = e.clave AND m.licitacion_id IS NULL",
            ([e[0] for e in enlaces], [e[1] for e in enlaces], [e[2] for e in enlaces]),
        )
        return cur.rowcount or 0


class FilaModificacion(TypedDict):
    """Una modificación de un expediente, como la enseña la ficha."""

    clave: str
    fuente: str
    numero: str | None
    contrato_ref: str | None
    lote_numero: str | None
    fecha_publicacion: str | None
    motivo_codigo: str | None
    motivo: str | None
    descripcion: str | None
    importe_modificacion: float | None
    importe_modificacion_base: str | None
    importe_final: float | None
    importe_final_base: str | None
    importe_aviso: float | None
    importe_aviso_base: str | None
    moneda: str | None
    plazo_modificacion: float | None
    plazo_final: float | None
    plazo_unidad: str | None
    aviso_original: str | None
    url: str | None


_SELECT_FICHA = (
    "SELECT m.clave, m.fuente, m.numero, m.contrato_ref, m.lote_numero, m.fecha_publicacion, "
    "m.motivo_codigo, m.motivo, m.descripcion, m.importe_modificacion, "
    "m.importe_modificacion_base, m.importe_final, m.importe_final_base, m.importe_aviso, "
    "m.importe_aviso_base, m.moneda, "
    "m.plazo_modificacion, m.plazo_final, m.plazo_unidad, m.aviso_original, m.url "
)
# Número de modificación como número cuando lo es («10» va detrás de «9»).
_ORDEN = (
    "ORDER BY m.fecha_publicacion NULLS LAST, "
    "CASE WHEN m.numero ~ '^[0-9]{1,9}$' THEN m.numero::int END NULLS LAST, m.clave"
)


def de_licitacion(licitacion_id: str) -> list[FilaModificacion]:
    """Las modificaciones del expediente, de la más antigua a la más reciente."""
    with connect_read() as c:
        cur = c.execute(
            f"{_SELECT_FICHA} FROM contrato_modificaciones m WHERE m.licitacion_id = %s {_ORDEN}",
            (licitacion_id,),
        )
        return typed_rows(FilaModificacion, rows_to_dicts(cur))


class FilaModificacionDeOrgano(FilaModificacion):
    licitacion_id: str


#: Techo de filas: las modificaciones de un órgano son decenas; esto solo evita
#: que un órgano anómalo traiga media tabla a la ficha.
_MAX_FILAS_ORGANO = 5_000


def del_organo_de(licitacion_id: str) -> list[FilaModificacionDeOrgano]:
    """Las modificaciones con importe final de todos los expedientes del órgano de ``licitacion_id``.

    El órgano es el del maestro (``organo_id``, ADR-032 §C) y, mientras el
    backfill no lo resuelva, el nombre plegado: el mismo predicado que la
    competencia esperada (``db.repositories.competencia_esperada``), por
    ``idx_lic_organo_id`` e ``idx_lic_organo_norm``. Un expediente sin órgano
    no tiene órgano con el que agregar: lista vacía.
    """
    plegado_e = organo_normalizado_sql("e")
    plegado_l = organo_normalizado_sql("l")
    with connect_read() as c:
        cur = c.execute(
            f"WITH e AS (SELECT e.organo_id, {plegado_e} AS norm FROM licitaciones e "
            "            WHERE e.id_externo = %s) "
            f"{_SELECT_FICHA}, m.licitacion_id FROM e "
            "JOIN licitaciones l ON (l.organo_id = e.organo_id "
            f"     OR (l.organo_id IS NULL AND {plegado_l} = e.norm)) "
            "JOIN contrato_modificaciones m ON m.licitacion_id = l.id_externo "
            f"WHERE m.importe_final IS NOT NULL {_ORDEN} LIMIT %s",
            (licitacion_id, _MAX_FILAS_ORGANO),
        )
        return typed_rows(FilaModificacionDeOrgano, rows_to_dicts(cur))


class FilaAdjudicado(TypedDict):
    licitacion_id: str
    lote_numero: str | None
    importe_adjudicado: float | None


def adjudicado_por_lote(licitacion_ids: Sequence[str]) -> list[FilaAdjudicado]:
    """Los importes adjudicados distintos de cada expediente y lote (``None`` = sin lote).

    Distintos: una UTE publica una fila por miembro con el mismo importe.
    """
    if not licitacion_ids:
        return []
    with connect_read() as c:
        cur = c.execute(
            "SELECT DISTINCT a.licitacion_id, lo.numero AS lote_numero, a.importe_adjudicado "
            "FROM adjudicaciones a LEFT JOIN lotes lo ON lo.id = a.lote_id "
            "WHERE a.licitacion_id = ANY(%s)",
            (list(licitacion_ids),),
        )
        return typed_rows(FilaAdjudicado, rows_to_dicts(cur))


def expedientes_de_avisos(ids: Sequence[str]) -> dict[str, str]:
    """``{id_externo: expediente}`` de los ``ids`` que están en ``licitaciones``.

    El expediente es la canónica cuando la fila es una republicación
    **confirmada** de otra (``licitaciones_duplicados``), y la propia fila si
    no: el aviso original de TED de un contrato que también publica PLACSP es
    el mismo expediente que la fila de PLACSP. Una marca ``pending`` no basta,
    porque aquí se sustituye el expediente, no se avisa (como en
    ``db.repositories.dedupe.canonical_for``).
    """
    if not ids:
        return {}
    with connect_read() as c:
        cur = c.execute(
            "SELECT DISTINCT ON (l.id_externo) l.id_externo, "
            "       COALESCE(d.canonical_id, l.id_externo) AS expediente "
            "FROM licitaciones l "
            "LEFT JOIN licitaciones_duplicados d "
            "  ON d.licitacion_id = l.id_externo AND d.status = 'confirmed' "
            "WHERE l.id_externo = ANY(%s) "
            "ORDER BY l.id_externo, d.confianza DESC NULLS LAST",
            (list(ids),),
        )
        return {str(fila[0]): str(fila[1]) for fila in cur.fetchall()}


def expedientes_de_avisos_previos(identificadores: Sequence[str]) -> dict[str, str]:
    """``{notice-identifier: expediente}`` de avisos de modificación de TED ya enlazados.

    Lo que permite enlazar una cadena: el BT-1501 de la segunda modificación de
    un contrato es el UUID del aviso de la primera, no el de la adjudicación.
    """
    if not identificadores:
        return {}
    with connect_read() as c:
        cur = c.execute(
            "SELECT identificador_aviso, licitacion_id FROM contrato_modificaciones "
            "WHERE identificador_aviso = ANY(%s) AND licitacion_id IS NOT NULL",
            (list(identificadores),),
        )
        return {str(fila[0]): str(fila[1]) for fila in cur.fetchall()}
