"""SQL de la búsqueda global de la paleta ⌘K (F1.2).

Cuatro consultas cortas, una por tipo, cada una con su ``LIMIT``. Van juntas
aquí y no repartidas por los repositorios de cada entidad porque comparten la
única restricción que de verdad las gobierna: **la paleta se abre con una
tecla**, así que ninguna puede tardar. Todas atacan un índice y ninguna hace
un ``COUNT(*)``.

El plegado de acentos usa ``fold_expr``, el mismo que el listado: si aquí se
plegara distinto, buscar «alcala» en la paleta y en el listado daría
resultados diferentes para el mismo órgano.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import FOLD_TABLE, fold_expr, organo_normalizado_sql

__all__ = ["BusquedaRepository"]


def _patron(termino: str) -> str:
    """El término plegado y en minúsculas, listo para un ``LIKE`` por prefijo
    o subcadena. Los comodines del usuario se escapan: escribir ``%`` en la
    paleta no puede convertirse en «tráemelo todo»."""
    limpio = termino.strip().translate(FOLD_TABLE).lower()
    escapado = limpio.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escapado}%"


class BusquedaRepository:
    """Las cuatro consultas de la paleta."""

    def expedientes(self, termino: str, limite: int) -> list[dict[str, Any]]:
        """Por id externo o por título.

        El id va primero y sin plegar: quien pega un `id_externo` quiere ese
        expediente, y la coincidencia exacta encabeza el resultado.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT id_externo AS id, titulo, organo_contratacion AS subtitulo "
                "FROM licitaciones "
                "WHERE id_externo = %s "
                "UNION ALL "
                "SELECT id_externo, titulo, organo_contratacion FROM licitaciones "
                f"WHERE id_externo <> %s AND {fold_expr('titulo')} LIKE %s "
                "ORDER BY 1 "
                "LIMIT %s",
                (termino.strip(), termino.strip(), _patron(termino), limite),
            )
            return rows_to_dicts(cur)

    def empresas(self, termino: str, limite: int) -> list[dict[str, Any]]:
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, nombre_canonico AS titulo, nif AS subtitulo FROM empresas "
                f"WHERE {fold_expr('nombre_canonico')} LIKE %s "
                "ORDER BY nombre_canonico LIMIT %s",
                (_patron(termino), limite),
            )
            return rows_to_dicts(cur)

    def empresa_por_nif(self, nif: str) -> dict[str, Any] | None:
        """Identificación exacta por NIF. Sin ``LIKE``: es una clave."""
        with connect_read() as c:
            cur = c.execute(
                "SELECT id, nombre_canonico, nif FROM empresas WHERE upper(nif) = %s LIMIT 1",
                (nif.strip().upper(),),
            )
            filas = rows_to_dicts(cur)
        return filas[0] if filas else None

    def organos(self, termino: str, limite: int) -> list[dict[str, Any]]:
        """Órganos distintos que casan, con cuántos expedientes tienen.

        Devuelve el nombre **normalizado** como id: es la identidad del órgano
        mientras no exista el maestro (C1.2), y es la misma clave con la que se
        siguen como cuenta objetivo (F1.5). Si aquí se devolviera el nombre
        crudo, seguir un órgano desde la paleta crearía una cuenta distinta de
        seguirlo desde Mercado.
        """
        normalizado = organo_normalizado_sql("l")
        with connect_read() as c:
            cur = c.execute(
                f"SELECT {normalizado} AS id, "
                "       min(l.organo_contratacion) AS titulo, "
                "       COUNT(*)::text AS subtitulo "
                "FROM licitaciones l "
                f"WHERE {fold_expr('l.organo_contratacion')} LIKE %s "
                f"GROUP BY {normalizado} "
                "ORDER BY COUNT(*) DESC LIMIT %s",
                (_patron(termino), limite),
            )
            return rows_to_dicts(cur)

    def oportunidades(
        self, termino: str, organization_id: int, limite: int
    ) -> list[dict[str, Any]]:
        """Oportunidades de **esta** organización, por título del expediente.

        El ``organization_id`` va en el ``WHERE`` y no es opcional: es la
        única de las cuatro consultas con datos de un equipo, y una búsqueda
        que se olvidara del ámbito enseñaría el pipeline de otra empresa.
        """
        with connect_read() as c:
            cur = c.execute(
                "SELECT p.id::text AS id, l.titulo, p.status AS subtitulo "
                "FROM pursuits p "
                "JOIN licitaciones l ON l.id_externo = p.licitacion_id "
                "WHERE p.organization_id = %s "
                f"  AND ({fold_expr('l.titulo')} LIKE %s OR p.licitacion_id = %s) "
                "ORDER BY p.updated_at DESC LIMIT %s",
                (organization_id, _patron(termino), termino.strip(), limite),
            )
            return rows_to_dicts(cur)
