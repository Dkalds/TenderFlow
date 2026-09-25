"""CRUD para notificaciones in-app y seguimiento de lecturas.

Modelo simple:
  - Las "notificaciones" son licitaciones nuevas desde la última visita
    (derivadas de ``licitaciones.fecha_publicacion``).
  - ``notification_reads`` almacena qué notificaciones ha visto cada usuario
    para calcular el badge de no leídas.
  - Un ``notification_id`` es simplemente el ``id_externo`` de la licitación.

Desde v129 (ADR-030 fase 2) ``notification_reads`` y ``user_notifications``
llevan ``user_id`` junto a ``user_key``: se escriben los dos y la lectura es
dual (ver ``db/repositories/watchlist.py``).
"""

from __future__ import annotations

from db.database import connect, connect_read, now_utc_iso

#: Predicado de identidad dual. Parámetros: ``(user_id, user_key, user_id)``.
_IDENT = "(user_id = %s OR (user_key = %s AND (user_id IS NULL OR %s::int IS NULL)))"

# Las dos lecturas de este módulo (`get_unread_ids`, `get_last_seen_ts`) van
# por el pool de lectura. Iban por el de escritura —`BEGIN` + consulta +
# `COMMIT` para un SELECT— y, además, así `GET /notifications` puede hacer todas
# sus lecturas en una sola conexión con `db.connection.lecturas_agrupadas`, que
# solo agrupa lo que pasa por `connect_read`. Leer lo que otra petición acaba de
# confirmar por el pool de escritura no cambia: es la misma base de datos.


def mark_read(user_key: str, notification_id: str, *, user_id: int | None = None) -> None:
    """Marca una notificación como leída para el usuario (idempotente)."""
    with connect() as c:
        c.execute(
            """
            INSERT INTO notification_reads (user_key, user_id, notification_id, read_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(user_key, notification_id) DO NOTHING
            """,
            (user_key, user_id, notification_id, now_utc_iso()),
        )


def mark_all_read(
    user_key: str, notification_ids: list[str], *, user_id: int | None = None
) -> None:
    """Marca una lista de notificaciones como leídas en una transacción."""
    if not notification_ids:
        return
    ts = now_utc_iso()
    with connect() as c:
        c.executemany(
            "INSERT INTO notification_reads (user_key, user_id, notification_id, read_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT(user_key, notification_id) DO NOTHING",
            [(user_key, user_id, nid, ts) for nid in notification_ids],
        )


def get_unread_ids(
    user_key: str, candidate_ids: list[str], *, user_id: int | None = None
) -> list[str]:
    """Devuelve los IDs de ``candidate_ids`` que el usuario NO ha leído."""
    if not candidate_ids:
        return []
    with connect_read() as c:
        placeholders = ",".join(["%s"] * len(candidate_ids))
        cur = c.execute(
            "SELECT notification_id FROM notification_reads "
            f"WHERE {_IDENT} AND notification_id IN (" + placeholders + ")",
            [user_id, user_key, user_id, *candidate_ids],
        )
        read_ids = {row[0] for row in cur.fetchall()}
    return [nid for nid in candidate_ids if nid not in read_ids]


def count_unread(user_key: str, candidate_ids: list[str], *, user_id: int | None = None) -> int:
    """Devuelve el número de notificaciones no leídas."""
    return len(get_unread_ids(user_key, candidate_ids, user_id=user_id))


def get_last_seen_ts(user_key: str, *, user_id: int | None = None) -> str | None:
    """Devuelve la fecha de la notificación más reciente leída, o None."""
    with connect_read() as c:
        row = c.execute(
            f"SELECT MAX(read_at) FROM notification_reads WHERE {_IDENT}",
            (user_id, user_key, user_id),
        ).fetchone()
    return row[0] if row else None


#: ``notification_id`` reservado para la marca de «visto todo» (F5.4). No es un
#: ``id_externo`` —ninguno empieza por doble guion bajo—, así que no puede
#: chocar con una lectura real ni aparecer como «leída» en la campana.
MARCA_VISITA = "__ultima_visita__"


def marcar_visita(user_key: str, *, user_id: int | None = None) -> str:
    """Mueve la última visita a ahora sin marcar ninguna notificación concreta.

    La última visita es ``MAX(read_at)`` de ``notification_reads``
    (:func:`get_last_seen_ts`), y hasta ahora solo avanzaba leyendo algo en la
    campana: «marcar todo como visto» en el Resumen no tenía qué escribir. Se
    guarda como una fila más con un ``notification_id`` reservado
    (:data:`MARCA_VISITA`) y se **actualiza** en cada llamada, así que no
    crece: una fila por usuario, sin migración.

    Devuelve la marca escrita.
    """
    ahora = now_utc_iso()
    with connect() as c:
        c.execute(
            "INSERT INTO notification_reads (user_key, user_id, notification_id, read_at) "
            "VALUES (%s, %s, %s, %s) "
            "ON CONFLICT(user_key, notification_id) DO UPDATE SET "
            "read_at = excluded.read_at, user_id = COALESCE(excluded.user_id, "
            "notification_reads.user_id)",
            (user_key, user_id, MARCA_VISITA, ahora),
        )
    return ahora


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
    user_id: int | None = None,
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

    ``user_id`` (v129) se escribe junto a la clave. Cuando se conoce, la
    idempotencia se comprueba además por identidad dual: la clave única sigue
    tecleada por ``user_key`` y, tras un cambio de correo, no frenaría una
    segunda alerta del mismo expediente bajo la clave nueva.
    """
    with connect() as c:
        if user_id is not None and licitacion_id is not None:
            repetida = c.execute(
                f"SELECT 1 FROM user_notifications WHERE {_IDENT} "
                "AND licitacion_id = %s AND type = %s LIMIT 1",
                (user_id, user_key, user_id, licitacion_id, type_),
            ).fetchone()
            if repetida is not None:
                return False
        cur = c.execute(
            "INSERT INTO user_notifications "
            "(user_key, user_id, created_at, type, title, body, licitacion_id, rule_id, "
            " organization_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT(user_key, licitacion_id, type) DO NOTHING",
            (
                user_key,
                user_id,
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
