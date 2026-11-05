"""SQL de ``mat_clusters``: lo que lee y escribe ``scheduler/aggregates_precompute``.

Bajó aquí desde el job (ADR-022, whitelist TID251). El cómputo de los
clusters sigue en el job; esto solo carga el corpus y reemplaza la tabla.
"""

from __future__ import annotations

from typing import Any, cast

from db.database import connect, connect_read
from db.sql_fragments import technology_observed_sql

#: Filas por INSERT multi-fila.
INSERT_CHUNK = 500


def _insert_batched(conn: Any, sql_prefix: str, columns: int, rows: list[tuple[Any, ...]]) -> None:
    """Inserta ``rows`` en bloques de ``INSERT_CHUNK`` con VALUES multi-fila.

    ``executemany`` emite una sentencia (y un round-trip de red) por fila: a
    cientos de ms por fila contra un backend remoto, miles de filas son minutos.
    Un INSERT multi-fila por bloque reduce los round-trips de N a N/``INSERT_CHUNK``.
    """
    for i in range(0, len(rows), INSERT_CHUNK):
        chunk = rows[i : i + INSERT_CHUNK]
        placeholders = ", ".join(f"({', '.join(['%s'] * columns)})" for _ in chunk)
        values = [v for row in chunk for v in row]
        conn.execute(f"{sql_prefix} VALUES {placeholders}", values)


def filas_para_clustering() -> list[tuple[str, str, str]]:
    """``(id_externo, titulo, descripción recortada)`` de los últimos 12 meses.

    Tope de 50 000 filas para acotar el cómputo. El alias ``l`` existe para
    interpolar el predicado canónico: ``technology_observed_sql`` siempre
    califica la columna, porque el índice parcial de v84 se acopla a su texto.
    """
    cutoff_sql = "l.fecha_publicacion >= to_char(CURRENT_DATE - INTERVAL '12 months', 'YYYY-MM-DD')"
    with connect_read() as conn:
        return cast(
            "list[tuple[str, str, str]]",
            conn.execute(
                f"""
            SELECT l.id_externo, l.titulo, SUBSTR(l.descripcion, 1, 500)
            FROM licitaciones l
            WHERE l.titulo IS NOT NULL
              AND {technology_observed_sql()}
              AND (l.fecha_publicacion IS NULL OR {cutoff_sql})
            ORDER BY l.fecha_publicacion DESC
            LIMIT 50000
            """
            ).fetchall(),
        )


def reemplazar_clusters(rows: list[dict[str, Any]]) -> None:
    """Reemplaza ``mat_clusters`` entera en una sola transacción."""
    with connect() as conn:
        conn.execute("DELETE FROM mat_clusters")
        if rows:
            _insert_batched(
                conn,
                "INSERT INTO mat_clusters (id_externo, cluster_id, cluster_label, updated_at)",
                4,
                [
                    (r["id_externo"], r["cluster_id"], r["cluster_label"], r["updated_at"])
                    for r in rows
                ],
            )
