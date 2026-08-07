"""Persistencia de los descartes del Radar (tabla ``radar_dismissals``).

El Radar guardaba los descartes en ``React.useState``, así que el triaje se
perdía al recargar (invariante 2 de ``docs/frontend-data-invariants.md``: el
estado de usuario es server-side). Este módulo es su respaldo.

**Todas** las consultas filtran por ``user_key``. La tabla es user-scoped y el
repositorio se defiende solo: no delega el control de propiedad en la ruta que
lo llame, que es justo el hueco de aislamiento que
``tests/test_user_key_sql_isolation.py`` audita en ``db/watchlist.py``.
"""

from __future__ import annotations

from db.database import connect, connect_read


def add(user_key: str, id_externo: str) -> None:
    """Marca una licitación como descartada por el usuario.

    Idempotente: la clave primaria es ``(user_key, id_externo)``, así que
    descartar dos veces no duplica ni falla.
    """
    with connect() as c:
        c.execute(
            "INSERT INTO radar_dismissals (user_key, id_externo) VALUES (%s, %s) "
            "ON CONFLICT (user_key, id_externo) DO NOTHING",
            (user_key, id_externo),
        )


def remove(user_key: str, id_externo: str) -> bool:
    """Deshace un descarte. ``True`` si había algo que deshacer."""
    with connect() as c:
        cur = c.execute(
            "DELETE FROM radar_dismissals WHERE user_key = %s AND id_externo = %s",
            (user_key, id_externo),
        )
        return bool(cur.rowcount > 0)


def list_ids(user_key: str) -> list[str]:
    """Devuelve los ``id_externo`` descartados por el usuario, recientes primero."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT id_externo FROM radar_dismissals WHERE user_key = %s ORDER BY created_at DESC",
            (user_key,),
        )
        return [str(row[0]) for row in cur.fetchall()]
