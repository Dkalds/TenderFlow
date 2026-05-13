"""CRUD para notificaciones in-app y seguimiento de lecturas.

Modelo simple:
  - Las "notificaciones" son licitaciones nuevas desde la última visita
    (derivadas de ``licitaciones.fecha_publicacion``).
  - ``notification_reads`` almacena qué notificaciones ha visto cada usuario
    para calcular el badge de no leídas.
  - Un ``notification_id`` es simplemente el ``id_externo`` de la licitación.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, now_utc_iso


def mark_read(user_key: str, notification_id: str) -> None:
    """Marca una notificación como leída para el usuario (idempotente)."""
    with connect() as c:
        c.execute(
            """
            INSERT OR IGNORE INTO notification_reads (user_key, notification_id, read_at)
            VALUES (?, ?, ?)
            """,
            (user_key, notification_id, now_utc_iso()),
        )


def mark_all_read(user_key: str, notification_ids: list[str]) -> None:
    """Marca una lista de notificaciones como leídas en una transacción."""
    if not notification_ids:
        return
    ts = now_utc_iso()
    with connect() as c:
        c.executemany(
            "INSERT OR IGNORE INTO notification_reads (user_key, notification_id, read_at) "
            "VALUES (?, ?, ?)",
            [(user_key, nid, ts) for nid in notification_ids],
        )


def get_unread_ids(user_key: str, candidate_ids: list[str]) -> list[str]:
    """Devuelve los IDs de ``candidate_ids`` que el usuario NO ha leído."""
    if not candidate_ids:
        return []
    with connect() as c:
        placeholders = ",".join("?" * len(candidate_ids))
        cur = c.execute(
            f"SELECT notification_id FROM notification_reads "
            f"WHERE user_key = ? AND notification_id IN ({placeholders})",
            [user_key, *candidate_ids],
        )
        read_ids = {row[0] for row in cur.fetchall()}
    return [nid for nid in candidate_ids if nid not in read_ids]


def count_unread(user_key: str, candidate_ids: list[str]) -> int:
    """Devuelve el número de notificaciones no leídas."""
    return len(get_unread_ids(user_key, candidate_ids))


def get_last_seen_ts(user_key: str) -> str | None:
    """Devuelve la fecha de la notificación más reciente leída, o None."""
    with connect() as c:
        row = c.execute(
            "SELECT MAX(read_at) FROM notification_reads WHERE user_key = ?",
            (user_key,),
        ).fetchone()
    return row[0] if row else None
