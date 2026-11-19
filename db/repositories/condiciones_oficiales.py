"""Lectura de las condiciones oficiales de CODICE de un expediente (v148).

La escritura vive en ``db/upsert.py`` (``_replace_condiciones``), dentro de la
transacción del upsert de licitaciones: es lo que la hace idempotente con la
misma red que el resto de la ingesta. Aquí solo se lee.
"""

from __future__ import annotations

from collections.abc import Sequence
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


#: Lo que :meth:`CondicionesOficialesRepository.get` devuelve por expediente:
#: claves heterogéneas (listas de filas, títulos de lotes, columnas sueltas).
_Datos = dict[str, Any]


def _vacio() -> _Datos:
    return {"criterios": [], "garantias": [], "solvencia": [], "lotes": {}, "actualizado": None}


class CondicionesOficialesRepository:
    """Repositorio fino de ``licitacion_criterios_adjudicacion``,
    ``licitacion_garantias`` y ``licitacion_solvencia``."""

    def get(self, licitacion_id: str) -> _Datos:
        """Las tres familias del expediente, los títulos de sus lotes y la fecha.

        Devuelve ``{"criterios", "garantias", "solvencia"}`` como listas de
        filas, ``"lotes"`` como ``{numero: titulo}`` (para rotular cada ámbito
        sin otra consulta), ``"actualizado"`` —la ``fecha_extraccion`` más
        reciente de las tres familias, o ``None`` si no hay ninguna fila—,
        ``"existe"`` (si el expediente está en ``licitaciones``), ``"url"``, el
        enlace a su publicación en la Plataforma, ``"valor_estimado"``,
        ``"tipo_contrato"`` (crudo), ``"fecha_publicacion"``, ``"nuts_code"`` y
        ``"tipos_anuncio"``, con los que se calcula el plazo del recurso especial.

        Sin las tablas (código desplegado antes que v148) responde como un
        expediente sin condiciones, que es lo cierto: no hay ninguna guardada.
        Cualquier otro error de la base sube tal cual.
        """
        return self.get_varios([licitacion_id])[licitacion_id]

    def get_varios(self, licitacion_ids: Sequence[str]) -> dict[str, _Datos]:
        """:meth:`get` de varios expedientes: cinco lecturas en total, no por expediente.

        Cada id pedido tiene entrada, con ``"existe": False`` si no está en
        ``licitaciones``. Lo usan los recordatorios de plazo de recurso, que
        miran todos los favoritos y pursuits recientes de una pasada.
        """
        ids = list(dict.fromkeys(licitacion_ids))
        claves = (
            "url",
            "valor_estimado",
            "tipo_contrato",
            "fecha_publicacion",
            "nuts_code",
            "tipos_anuncio",
        )
        bases: dict[str, dict[str, object]] = {
            lic: {"existe": False, **dict.fromkeys(claves)} for lic in ids
        }
        if ids:
            with connect_read() as c:
                for fila in c.execute(
                    f"SELECT id_externo, {', '.join(claves)} FROM licitaciones "
                    "WHERE id_externo = ANY(%s)",
                    (ids,),
                ).fetchall():
                    bases[str(fila[0])] = {
                        "existe": True,
                        **dict(zip(claves, fila[1:], strict=True)),
                    }
        existentes = [lic for lic in ids if bases[lic]["existe"]]
        try:
            leidos = self._leer(existentes)
        except pg_errors.UndefinedTable:
            leidos = {}
        return {lic: {**leidos.get(lic, _vacio()), **bases[lic]} for lic in ids}

    def solvencia_de(self, licitacion_ids: list[str]) -> dict[str, list[dict[str, object]]]:
        """Las filas de ``licitacion_solvencia`` de varios expedientes, por id.

        Mismas columnas y orden que la familia ``solvencia`` de :meth:`get`;
        los expedientes sin solvencia publicada no aparecen. Es la lectura en
        lote del resumen diario (B3 del plan 2026-10): solo la solvencia,
        porque es lo único de las condiciones que el correo contrasta.

        Sin la tabla (código desplegado antes que v148) responde vacío, igual
        que :meth:`get`.
        """
        if not licitacion_ids:
            return {}
        try:
            with connect_read() as c:
                filas = rows_to_dicts(
                    c.execute(
                        f"SELECT licitacion_id, {_COLUMNAS_SOLVENCIA} FROM licitacion_solvencia "
                        f"WHERE licitacion_id = ANY(%s) {_ORDEN}",
                        (list(licitacion_ids),),
                    )
                )
        except pg_errors.UndefinedTable:
            return {}
        por_id: dict[str, list[dict[str, object]]] = {}
        for fila in filas:
            por_id.setdefault(str(fila.pop("licitacion_id")), []).append(fila)
        return por_id

    def _leer(self, licitacion_ids: list[str]) -> dict[str, _Datos]:
        """Las tres familias y los lotes de esos expedientes, por id: una lectura por tabla."""
        if not licitacion_ids:
            return {}
        leidos = {lic: _vacio() for lic in licitacion_ids}
        with connect_read() as c:
            for familia, tabla, columnas in (
                ("criterios", "licitacion_criterios_adjudicacion", _COLUMNAS_CRITERIOS),
                ("garantias", "licitacion_garantias", _COLUMNAS_GARANTIAS),
                ("solvencia", "licitacion_solvencia", _COLUMNAS_SOLVENCIA),
            ):
                # El ORDER BY global conserva el orden de cada expediente al agrupar.
                for fila in rows_to_dicts(
                    c.execute(
                        f"SELECT licitacion_id, {columnas} FROM {tabla} "
                        f"WHERE licitacion_id = ANY(%s) {_ORDEN}",
                        (licitacion_ids,),
                    )
                ):
                    leidos[str(fila.pop("licitacion_id"))][familia].append(fila)
            con_filas = [
                lic
                for lic, datos in leidos.items()
                if datos["criterios"] or datos["garantias"] or datos["solvencia"]
            ]
            if con_filas:
                for lic, numero, titulo in c.execute(
                    "SELECT licitacion_id, numero, titulo FROM lotes WHERE licitacion_id = ANY(%s)",
                    (con_filas,),
                ).fetchall():
                    leidos[str(lic)]["lotes"][str(numero)] = titulo
        for datos in leidos.values():
            fechas = [
                str(fila["fecha_extraccion"])
                for fila in (*datos["criterios"], *datos["garantias"], *datos["solvencia"])
                if fila.get("fecha_extraccion")
            ]
            datos["actualizado"] = max(fechas) if fechas else None
        return leidos
