"""Asignar su lote a las adjudicaciones ya guardadas sin re-ingerir el expediente.

Hasta 2026-10 el parser no leía el lote del ``cac:TenderResult`` (ver
``scraper/codice_parser.py::_lote_del_resultado``), así que ninguna adjudicación
de un expediente multilote tenía ``lote_id``. La ingesta corrige lo que vuelve a
publicarse, pero el bulk tarda más de dos horas por mes (escribe los documentos
de cada expediente uno a uno) y no puede reprocesar el histórico. Esto hace solo
lo que falta: poner ``lote_id`` a la fila que ya existe.

Se **actualiza en sitio**, no se borra y reinserta: la fila conserva su ``id``
y su ``empresa_id`` resuelto, y no hay que volver a pasar la resolución de
empresas. El emparejamiento es por ``(licitacion_id, nif, importe_adjudicado)``
—la misma clave que la unique ``..._sin_lote``— o por nombre cuando no hay NIF;
una fila que no casa se queda como estaba.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from db.database import connect, connect_read


@dataclass(frozen=True)
class AsignacionLote:
    """Una adjudicación tal como la publica la fuente, con el número de su lote."""

    licitacion_id: str
    nombre: str
    nif: str | None
    importe_adjudicado: float | None
    lote_numero: str


def multilote_sin_lote() -> set[str]:
    """Expedientes con dos o más lotes y alguna adjudicación sin ``lote_id``."""
    with connect_read() as conn:
        rows = conn.execute(
            "SELECT DISTINCT a.licitacion_id FROM adjudicaciones a "
            "WHERE a.lote_id IS NULL AND a.licitacion_id IN ("
            "  SELECT licitacion_id FROM lotes GROUP BY licitacion_id HAVING count(*) >= 2"
            ")"
        ).fetchall()
    return {str(row[0]) for row in rows}


# Con NIF casa por NIF; sin él, por nombre. `IS NOT DISTINCT FROM` para que un
# importe NULL case con NULL, que es como lo guardó la ingesta.
#
# El importe se compara a la precisión de `real` (float4), no exacto. La
# columna fue `real` en producción hasta `v155`, y lo que guardó entonces ya
# está redondeado para siempre: 39.567,94 € quedó en 39.567,94140625, y el
# float8 que lee el parser del XML no es igual a eso. Con igualdad exacta, toda
# adjudicación cuyo importe tuviera céntimos que float4 no representa se quedaba
# sin lote (113 de las 121 pendientes, medido el 2026-10-23). Bajar los dos
# lados a `real` casa las filas viejas y las que ya se escriben en float8.
_ASIGNAR_SQL = (
    "UPDATE adjudicaciones a SET lote_id = lo.id "
    "FROM lotes lo "
    "WHERE lo.licitacion_id = a.licitacion_id AND lo.numero = %(lote_numero)s "
    "  AND a.licitacion_id = %(licitacion_id)s AND a.lote_id IS NULL "
    "  AND a.importe_adjudicado::real IS NOT DISTINCT FROM %(importe_adjudicado)s::real "
    "  AND CASE WHEN %(nif)s::text IS NOT NULL THEN a.nif = %(nif)s "
    "           ELSE a.nif IS NULL AND a.nombre = %(nombre)s END"
)


def asignar_lotes(asignaciones: Sequence[AsignacionLote]) -> int:
    """Pone ``lote_id`` a las filas que casan; devuelve cuántas cambiaron.

    Una asignación ambigua —la misma empresa por el mismo importe en dos
    lotes del expediente— no se aplica: la unique ``..._sin_lote`` dejó una
    sola fila para las dos y no hay forma de saber de cuál era. La siguiente
    ingesta de ese expediente las reescribe enteras, ya separadas.
    """
    claves: dict[tuple[str, str | None, str, float | None], set[str]] = {}
    for a in asignaciones:
        clave = (a.licitacion_id, a.nif, a.nombre if a.nif is None else "", a.importe_adjudicado)
        claves.setdefault(clave, set()).add(a.lote_numero)

    cambiadas = 0
    with connect() as conn:
        for (licitacion_id, nif, nombre, importe), lotes in claves.items():
            if len(lotes) != 1:
                continue
            cur = conn.execute(
                _ASIGNAR_SQL,
                {
                    "licitacion_id": licitacion_id,
                    "nif": nif,
                    "nombre": nombre,
                    "importe_adjudicado": importe,
                    "lote_numero": next(iter(lotes)),
                },
            )
            cambiadas += cur.rowcount or 0
    return cambiadas
