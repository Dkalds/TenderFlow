"""CRUD para notificaciones in-app y seguimiento de lecturas.

Modelo simple:
  - Las "notificaciones" son licitaciones nuevas desde la última visita
    (derivadas de ``licitaciones.fecha_publicacion``).
  - ``notification_reads`` almacena qué notificaciones ha visto cada usuario
    para calcular el badge de no leídas.
  - Un ``notification_id`` es simplemente el ``id_externo`` de la licitación.
"""

from __future__ import annotations

from db.database import connect, now_utc_iso


def mark_read(user_key: str, notification_id: str) -> None:
    """Marca una notificación como leída para el usuario (idempotente)."""
    with connect() as c:
        c.execute(
            """
            INSERT INTO notification_reads (user_key, notification_id, read_at)
            VALUES (%s, %s, %s)
            ON CONFLICT(user_key, notification_id) DO NOTHING
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
            "INSERT INTO notification_reads (user_key, notification_id, read_at) "
            "VALUES (%s, %s, %s) ON CONFLICT(user_key, notification_id) DO NOTHING",
            [(user_key, nid, ts) for nid in notification_ids],
        )


def get_unread_ids(user_key: str, candidate_ids: list[str]) -> list[str]:
    """Devuelve los IDs de ``candidate_ids`` que el usuario NO ha leído."""
    if not candidate_ids:
        return []
    with connect() as c:
        placeholders = ",".join(["%s"] * len(candidate_ids))
        cur = c.execute(
            "SELECT notification_id FROM notification_reads "
            "WHERE user_key = %s AND notification_id IN (" + placeholders + ")",
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
            "SELECT MAX(read_at) FROM notification_reads WHERE user_key = %s",
            (user_key,),
        ).fetchone()
    return row[0] if row else None


def insert_user_notification(
    *,
    user_key: str,
    type_: str,
    title: str,
    body: str | None,
    licitacion_id: str | None,
    organization_id: int,
    rule_id: int | None = None,
    created_at: str | None = None,
) -> bool:
    """Escribe una alerta in-app en ``user_notifications``; idempotente.

    La tabla lleva ``UNIQUE(user_key, licitacion_id, type)``, así que quien
    llama codifica en ``type_`` lo que hace única a la alerta (``deadline_7``,
    ``pursuit_asignada``, ``adjudicacion_detectada``…) y repetir la llamada no
    duplica la fila. Devuelve ``True`` sólo si insertó.

    Es la única escritura de alertas de producto fuera de los jobs de reglas:
    hasta ahora cada productor (reglas, recordatorios) repetía su propio
    ``INSERT`` con el mismo ``ON CONFLICT``, y un tercero —las asignaciones de
    pursuits— habría sido la tercera copia.

    ``organization_id`` no admite ``None``: una alerta sin organización queda
    fuera del alcance de cualquier lectura con ámbito y el usuario no la ve en
    ningún sitio. Los tres productores (reglas, recordatorios, pursuits) la
    tienen a mano; que sea obligatoria impide que un cuarto la olvide.
    """
    with connect() as c:
        cur = c.execute(
            "INSERT INTO user_notifications "
            "(user_key, created_at, type, title, body, licitacion_id, rule_id, organization_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(user_key, licitacion_id, type) DO NOTHING",
            (
                user_key,
                created_at or now_utc_iso(),
                type_,
                title,
                body,
                licitacion_id,
                rule_id,
                organization_id,
            ),
        )
        return bool(cur.rowcount > 0)
