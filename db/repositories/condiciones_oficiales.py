"""Lectura de las condiciones oficiales de CODICE de un expediente (v149).

La escritura vive en ``db/upsert.py`` (``_replace_condiciones``), dentro de la
transacción del upsert de licitaciones: es lo que la hace idempotente con la
misma red que el resto de la ingesta. Aquí solo se lee.
"""

from __future__ import annotations

from typing import Any

from psycopg import errors as pg_errors

from db.database import connect_read
from db.repositories.base import rows_to_dicts

_COLUMNAS_CRITERIOS = (
    "lote_numero, orden, padre_orden, descripcion, peso, peso_pct, es_precio, "
    "tipo_codigo, subtipo_codigo, nota, fecha_extraccion"
)
_COLUMNAS_GARANTIAS = (
    "lote_numero, orden, tipo_codigo, porcentaje, importe, moneda, descripcion, fecha_extraccion"
)
_COLUMNAS_SOLVENCIA = (
    "lote_numero, orden, clase, tipo_codigo, descripcion, umbral_importe, moneda, fecha_extraccion"
)

#: Expediente primero, después cada lote en el orden natural de su número
#: cuando es numérico ("2" antes que "10") y alfabético si no lo es.
_ORDEN = (
    "ORDER BY lote_numero IS NOT NULL, "
    "CASE WHEN lote_numero ~ '^[0-9]+$' THEN lpad(lote_numero, 12, '0') ELSE lote_numero END, "
    "orden"
)


def _vacio() -> dict[str, Any]:
    return {"criterios": [], "garantias": [], "solvencia": [], "lotes": {}, "actualizado": None}


class CondicionesOficialesRepository:
    """Repositorio fino de ``licitacion_criterios_adjudicacion``,
    ``licitacion_garantias`` y ``licitacion_solvencia``."""

    def get(self, licitacion_id: str) -> dict[str, Any]:
        """Las tres familias del expediente, los títulos de sus lotes y la fecha.

        Devuelve ``{"criterios", "garantias", "solvencia"}`` como listas de
        filas, ``"lotes"`` como ``{numero: titulo}`` (para rotular cada ámbito
        sin otra consulta) y ``"actualizado"``, la ``fecha_extraccion`` más
        reciente de las tres familias o ``None`` si no hay ninguna fila.

        Sin las tablas (código desplegado antes que v149) responde como un
        expediente sin condiciones, que es lo cierto: no hay ninguna guardada.
        Cualquier otro error de la base sube tal cual.
        """
        try:
            return self._leer(licitacion_id)
        except pg_errors.UndefinedTable:
            return _vacio()

    def _leer(self, licitacion_id: str) -> dict[str, Any]:
        with connect_read() as c:
            criterios = rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS_CRITERIOS} FROM licitacion_criterios_adjudicacion "
                    f"WHERE licitacion_id = %s {_ORDEN}",
                    (licitacion_id,),
                )
            )
            garantias = rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS_GARANTIAS} FROM licitacion_garantias "
                    f"WHERE licitacion_id = %s {_ORDEN}",
                    (licitacion_id,),
                )
            )
            solvencia = rows_to_dicts(
                c.execute(
                    f"SELECT {_COLUMNAS_SOLVENCIA} FROM licitacion_solvencia "
                    f"WHERE licitacion_id = %s {_ORDEN}",
                    (licitacion_id,),
                )
            )
            lotes: dict[str, str | None] = {}
            if criterios or garantias or solvencia:
                filas = c.execute(
                    "SELECT numero, titulo FROM lotes WHERE licitacion_id = %s",
                    (licitacion_id,),
                ).fetchall()
                lotes = {str(numero): titulo for numero, titulo in filas}
        fechas = [
            str(fila["fecha_extraccion"])
            for fila in (*criterios, *garantias, *solvencia)
            if fila.get("fecha_extraccion")
        ]
        return {
            "criterios": criterios,
            "garantias": garantias,
            "solvencia": solvencia,
            "lotes": lotes,
            "actualizado": max(fechas) if fechas else None,
        }
