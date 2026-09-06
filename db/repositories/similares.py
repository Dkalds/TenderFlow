"""Lecturas para predecesor y expedientes similares (C1.3).

Todo el SQL vive aquí (ADR-022). El criterio —qué cuenta como predecesor, cómo
se ordenan los similares, cuándo se declara `metodo`— está en
``services/similares.py``.
"""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from db.sql_fragments import exclude_duplicados_presentacion_sql
from observability.logging import get_logger

log = get_logger(__name__)

#: Columnas que describen un candidato. Deliberadamente cortas: la ficha de
#: similares no es un listado completo, es una pista para abrir el expediente.
_COLS = (
    "l.id_externo, l.titulo, l.organo_contratacion, l.organo_id, l.cpv, "
    "l.importe, l.importe_base_sin_iva, l.estado, l.fecha_publicacion, l.fecha_limite"
)


def objetivo(id_externo: str) -> dict[str, Any] | None:
    """El expediente sobre el que se buscan predecesor y similares."""
    with connect_read() as c:
        filas = rows_to_dicts(
            c.execute(
                f"SELECT {_COLS}, l.descripcion FROM licitaciones l "
                "WHERE l.id_externo = %s LIMIT 1",
                (id_externo,),
            )
        )
    return filas[0] if filas else None


def candidatos_a_predecesor(
    *,
    id_externo: str,
    organo_id: int | None,
    organo_contratacion: str | None,
    cpv4: str | None,
    antes_de: str | None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Contratos **adjudicados** del MISMO órgano, anteriores, con CPV4 igual.

    Las tres condiciones son las que hacen que la palabra «predecesor» signifique
    algo: mismo comprador, mismo tipo de objeto, y antes en el tiempo. Sin la
    primera sería "un contrato parecido de cualquiera", que es lo que devuelven
    los similares y ya tiene su sitio.

    El órgano se compara por `organo_id` cuando el maestro lo resolvió (C1.2) y
    por texto cuando no: la misma lectura dual que la analítica, por el mismo
    motivo — un expediente sin resolver sigue siendo un expediente.
    """
    if not cpv4:
        return []
    condiciones = [
        "l.id_externo <> %s",
        "a.importe_adjudicado IS NOT NULL",
        "l.cpv LIKE %s",
        exclude_duplicados_presentacion_sql("l.id_externo"),
    ]
    params: list[Any] = [id_externo, f"{cpv4}%"]

    if organo_id is not None:
        condiciones.append("l.organo_id = %s")
        params.append(organo_id)
    elif organo_contratacion:
        condiciones.append("lower(btrim(l.organo_contratacion)) = lower(btrim(%s))")
        params.append(organo_contratacion)
    else:
        # Sin órgano no hay predecesor posible: devolverlo sería llamar
        # «predecesor» a un contrato de otro comprador.
        return []

    if antes_de:
        condiciones.append("COALESCE(l.fecha_publicacion, l.fecha_extraccion) < %s")
        params.append(antes_de)

    params.append(limit)
    sql = (
        f"SELECT {_COLS}, a.importe_adjudicado, a.nombre AS adjudicatario, "
        "       a.fecha_adjudicacion "
        "FROM licitaciones l "
        "JOIN adjudicaciones a ON a.licitacion_id = l.id_externo "
        "WHERE " + " AND ".join(condiciones) + " "
        "ORDER BY COALESCE(l.fecha_publicacion, l.fecha_extraccion) DESC "
        "LIMIT %s"
    )
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def candidatos_a_similar(
    *, id_externo: str, cpv4: str | None, limit: int = 100
) -> list[dict[str, Any]]:
    """Expedientes de CUALQUIER órgano con el mismo CPV4.

    A diferencia del predecesor, aquí el órgano no importa: la pregunta es «qué
    más se está comprando parecido a esto», y acotarla al mismo comprador la
    convertiría en la anterior.
    """
    if not cpv4:
        return []
    sql = (
        f"SELECT {_COLS} FROM licitaciones l "
        "WHERE l.id_externo <> %s AND l.cpv LIKE %s "
        f"  AND {exclude_duplicados_presentacion_sql('l.id_externo')} "
        "ORDER BY COALESCE(l.fecha_publicacion, l.fecha_extraccion) DESC "
        "LIMIT %s"
    )
    with connect_read() as c:
        return rows_to_dicts(c.execute(sql, (id_externo, f"{cpv4}%", limit)))
