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

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts

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

_LISTA_GROUP_ORDER = (
    "GROUP BY e.empresa_id, e.nombre_canonico, e.nif_canonico, e.es_ute, e.es_pyme, g.nombre "
    "ORDER BY importe_total DESC LIMIT %s OFFSET %s"
)


class EmpresasReadRepository:
    """Consultas de lectura del maestro de empresas."""

    def list_empresas(self, q: str | None, limit: int, offset: int) -> list[dict[str, Any]]:
        """Empresas canónicas con sus agregados de adjudicaciones.

        ``q`` busca en nombre canónico, NIF y aliases. Ordena por importe
        adjudicado total descendente.
        """
        sql = _LISTA_SELECT
        params: list[Any] = []
        if q:
            sql += _LISTA_WHERE_BUSQUEDA
            like = f"%{q.upper()}%"
            params.extend([like, like, like])
        sql += _LISTA_GROUP_ORDER
        params.extend([limit, offset])
        with connect_read() as c:
            return rows_to_dicts(c.execute(sql, params))

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
