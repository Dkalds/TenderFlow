"""Lecturas del maestro de empresas para la API (buscador y detalle).

Complementa ``db/empresas.py``, que es la cara de *escritura* del maestro
(resolución de entidades, aliases, cola de revisión) y trabaja sobre una
conexión abierta por quien orquesta el backfill. Aquí viven las dos consultas
de lectura que sirven ``GET /empresas`` y ``GET /empresas/{id}``, que abren su
propia conexión de solo lectura y no comparten transacción con nadie.

Existen como repositorio porque hasta 2026-09 vivían dentro de
``api/routes/empresas.py``: SQL crudo en la ruta, con ``connect_read``
importado en el router. ADR-022 dice que todo el SQL vive en ``db/``, y el
ratchet TID251 tenía ese fichero en la whitelist de excepciones legacy.
"""

from __future__ import annotations

from typing import Any, Literal

from db.database import connect_read
from db.repositories.base import rows_to_dicts

EmpresasOrderBy = Literal["nombre", "nif", "contratos", "importe"]
EmpresasOrderDir = Literal["asc", "desc"]

_LISTA_SELECT = (
    "SELECT e.empresa_id, e.nombre_canonico, e.nif_canonico, e.es_ute, e.es_pyme, "
    "       g.nombre AS grupo, "
    "       COUNT(a.id) AS n_adjudicaciones, "
    "       COALESCE(SUM(a.importe_adjudicado), 0) AS importe_total "
    "FROM empresas e "
    "LEFT JOIN grupos_empresariales g ON g.grupo_id = e.grupo_id "
    "LEFT JOIN adjudicaciones a ON a.empresa_id = e.empresa_id "
)

_LISTA_WHERE_BUSQUEDA = (
    "WHERE e.nombre_canonico LIKE %s OR e.nif_canonico LIKE %s "
    "OR e.empresa_id IN "
    "(SELECT empresa_id FROM empresa_aliases WHERE alias_normalizado LIKE %s) "
)

_LISTA_GROUP = (
    "GROUP BY e.empresa_id, e.nombre_canonico, e.nif_canonico, e.es_ute, e.es_pyme, g.nombre "
)

# Clave del contrato → expresión por la que ordenar. La tabla, y no el
# parámetro, es lo único que acaba concatenado en el SQL: el ``Literal`` de la
# ruta ya acota los valores que entran, pero un enum de Pydantic no defiende a
# la capa que construye la query, y esta tabla sí. ``contratos`` e ``importe``
# apuntan a los alias de salida del propio SELECT, que Postgres admite en
# ``ORDER BY`` (es lo que ya hacía el orden fijo por importe).
_ORDEN_EXPR: dict[str, str] = {
    "nombre": "LOWER(e.nombre_canonico)",
    "nif": "e.nif_canonico",
    "contratos": "n_adjudicaciones",
    "importe": "importe_total",
}

_COUNT_SELECT = "SELECT COUNT(*) FROM empresas e "


class EmpresasReadRepository:
    """Consultas de lectura del maestro de empresas."""

    def list_empresas(
        self,
        q: str | None,
        limit: int,
        offset: int,
        sort: EmpresasOrderBy = "importe",
        order: EmpresasOrderDir = "desc",
    ) -> tuple[list[dict[str, Any]], int]:
        """Página de empresas canónicas con sus agregados, y cuántas hay en total.

        ``q`` busca en nombre canónico, NIF y aliases. El total viaja con la
        página porque el buscador pagina: sin él la vista sólo puede decir
        cuántas filas ha recibido —«14 de 1.284» eran las 14 que cabían— y ese
        es justo el número que no responde a si queda algo detrás.

        Las dos consultas comparten conexión a propósito, por el mismo motivo
        que las cuatro de :meth:`get_empresa`: son la misma pantalla.
        """
        where = _LISTA_WHERE_BUSQUEDA if q else ""
        params: list[Any] = []
        if q:
            like = f"%{q.upper()}%"
            params.extend([like, like, like])

        # ``NULLS LAST`` en los dos sentidos: un NIF ausente no es el valor más
        # pequeño, es la fila de la que no se sabe el dato, y en el maestro esa
        # fila no debe encabezar la página en ninguno de los dos órdenes.
        # ``empresa_id`` desempata para que paginar sea estable: sin él, dos
        # empresas con el mismo importe pueden cruzarse entre la página 1 y la
        # 2 y una de ellas no aparece en ninguna.
        direction = "ASC" if order == "asc" else "DESC"
        orden = f"ORDER BY {_ORDEN_EXPR[sort]} {direction} NULLS LAST, e.empresa_id ASC "

        with connect_read() as c:
            rows = rows_to_dicts(
                c.execute(
                    _LISTA_SELECT + where + _LISTA_GROUP + orden + "LIMIT %s OFFSET %s",
                    [*params, limit, offset],
                )
            )
            total_row = c.execute(_COUNT_SELECT + where, params).fetchone()
        return rows, int(total_row[0] if total_row else 0)

    def get_empresa(self, empresa_id: int) -> dict[str, Any] | None:
        """Empresa con aliases, miembros de UTE y UTEs en las que participa.

        Las cuatro consultas comparten conexión a propósito: son la misma
        pantalla y pedir cuatro slots del pool para pintarla sería gratuito
        solo si el pool fuera infinito (tiene 12).
        """
        with connect_read() as c:
            rows = rows_to_dicts(
                c.execute(
                    "SELECT e.empresa_id, e.nombre_canonico, e.nif_canonico, e.es_ute, "
                    "       e.es_pyme, g.nombre AS grupo, e.created_at, e.updated_at "
                    "FROM empresas e "
                    "LEFT JOIN grupos_empresariales g ON g.grupo_id = e.grupo_id "
                    "WHERE e.empresa_id = %s",
                    (empresa_id,),
                )
            )
            if not rows:
                return None
            empresa = rows[0]
            empresa["aliases"] = rows_to_dicts(
                c.execute(
                    "SELECT alias_normalizado, nif_variante, fuente, confianza "
                    "FROM empresa_aliases WHERE empresa_id = %s ORDER BY id",
                    (empresa_id,),
                )
            )
            empresa["ute_miembros"] = rows_to_dicts(
                c.execute(
                    "SELECT m.empresa_id, m.nombre_canonico, m.nif_canonico "
                    "FROM ute_miembros u JOIN empresas m ON m.empresa_id = u.miembro_empresa_id "
                    "WHERE u.ute_empresa_id = %s",
                    (empresa_id,),
                )
            )
            empresa["participa_en_utes"] = rows_to_dicts(
                c.execute(
                    "SELECT u2.ute_empresa_id AS empresa_id, e2.nombre_canonico "
                    "FROM ute_miembros u2 JOIN empresas e2 ON e2.empresa_id = u2.ute_empresa_id "
                    "WHERE u2.miembro_empresa_id = %s",
                    (empresa_id,),
                )
            )
            return empresa


__all__ = ["EmpresasReadRepository"]
