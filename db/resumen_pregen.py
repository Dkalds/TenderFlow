"""Candidatas a la pre-generación nocturna del resumen IA (ADR-022: el SQL, aquí).

Dos de las tres fuentes de prioridad de la fase de pre-generación de
``scheduler/jobs/documentos_embeddings.py`` son SQL; la tercera —la banda
``Caliente`` del score— se calcula en ``services.analytics.scoring`` y no tiene
columna que leer, así que la pide el job al servicio.

Las dos se limitan a licitaciones **abiertas** (``shared.estados``): el resumen
sirve para decidir si presentarse, y pagar uno de una licitación ya resuelta es
gastar presupuesto en una pregunta que nadie va a hacer.
"""

from __future__ import annotations

from db.database import connect_read
from db.sql_fragments import iso_guard
from shared.estados import abierta_sql

#: Estados de pursuit que ya no piden trabajo sobre el expediente. Los mismos que
#: usan la cola de fichas y la de documentos para su prioridad de «demanda».
_PURSUIT_CERRADO = "('won', 'lost', 'withdrawn')"


def licitaciones_seguidas_abiertas(limit: int) -> list[str]:
    """Abiertas que alguien convirtió en oportunidad o marcó como favorita.

    Oportunidades antes que favoritas —es el mismo orden de «demanda» que la
    cola de fichas—, y dentro de cada grupo el plazo más cercano primero: es la
    que antes se va a abrir para decidir.
    """
    abierta = abierta_sql("l.estado")
    sql = (
        "SELECT l.id_externo FROM licitaciones l "
        "JOIN ("
        "  SELECT p.licitacion_id AS id_externo, 0 AS demanda FROM pursuits p "
        f"  WHERE p.status NOT IN {_PURSUIT_CERRADO} "
        "  UNION ALL "
        "  SELECT w.id_externo, 1 AS demanda FROM watchlist_items w"
        ") s ON s.id_externo = l.id_externo "
        f"WHERE {abierta} "
        "GROUP BY l.id_externo, l.fecha_limite "
        "ORDER BY MIN(s.demanda), l.fecha_limite ASC NULLS LAST, l.id_externo "
        "LIMIT %s"
    )
    with connect_read() as c:
        filas = c.execute(sql, (max(1, int(limit)),)).fetchall()
    return [str(fila[0]) for fila in filas]


def licitaciones_publicadas_desde(desde_iso: str, limit: int) -> list[str]:
    """Abiertas publicadas en o después de ``desde_iso``, las más recientes primero."""
    abierta = abierta_sql("estado")
    sql = (
        "SELECT id_externo FROM licitaciones "
        f"WHERE {abierta} AND {iso_guard('fecha_publicacion')} AND fecha_publicacion >= %s "
        "ORDER BY fecha_publicacion DESC, id_externo "
        "LIMIT %s"
    )
    with connect_read() as c:
        filas = c.execute(sql, (desde_iso, max(1, int(limit)))).fetchall()
    return [str(fila[0]) for fila in filas]
