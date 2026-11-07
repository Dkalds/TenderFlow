"""Consultas recientes del Investigador, por usuario (v176).

Las diez últimas frases que buscó cada persona, para ofrecérselas de nuevo en
cualquier navegador. Hasta v176 vivían en ``localStorage``.

La frase es la estrategia comercial de quien la escribe: este módulo no la
escribe en ningún log.
"""

from __future__ import annotations

from db.database import connect, connect_read

#: Cuántas se recuerdan. El frontend enseña las mismas (``MAX_HISTORY``).
MAX_CONSULTAS = 10

#: El techo de la columna (``CHECK`` de v176) y de ``SemanticSearchRequest.q``.
MAX_LARGO = 500


def listar(user_id: int) -> list[str]:
    """Las consultas de ``user_id``, la más reciente primero."""
    with connect_read() as c:
        filas = c.execute(
            "SELECT consulta FROM consultas_recientes WHERE user_id = %s "
            "ORDER BY usada_en DESC, consulta LIMIT %s",
            (user_id, MAX_CONSULTAS),
        ).fetchall()
    return [str(f[0]) for f in filas]


def registrar(user_id: int, consulta: str) -> list[str]:
    """Apunta ``consulta`` como la más reciente y devuelve la lista resultante.

    Repetir una consulta la sube al principio en vez de duplicarla (la PK es
    ``(user_id, consulta)``), y lo que pase de :data:`MAX_CONSULTAS` se borra en
    la misma transacción: la tabla no crece con el uso.
    """
    with connect() as c:
        c.execute(
            "INSERT INTO consultas_recientes (user_id, consulta) VALUES (%s, %s) "
            "ON CONFLICT (user_id, consulta) DO UPDATE SET usada_en = now()",
            (user_id, consulta),
        )
        c.execute(
            "DELETE FROM consultas_recientes WHERE user_id = %s AND consulta NOT IN ("
            " SELECT consulta FROM consultas_recientes WHERE user_id = %s"
            " ORDER BY usada_en DESC, consulta LIMIT %s)",
            (user_id, user_id, MAX_CONSULTAS),
        )
        filas = c.execute(
            "SELECT consulta FROM consultas_recientes WHERE user_id = %s "
            "ORDER BY usada_en DESC, consulta",
            (user_id,),
        ).fetchall()
    return [str(f[0]) for f in filas]


def borrar_de_usuario(user_id: int) -> None:
    """Borra el historial de ``user_id`` (RGPD art. 17, ``services/gdpr.py``)."""
    with connect() as c:
        c.execute("DELETE FROM consultas_recientes WHERE user_id = %s", (user_id,))
