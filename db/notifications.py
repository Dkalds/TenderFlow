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

from datetime import UTC, datetime
from typing import Any, Literal, TypedDict

from db.database import connect, connect_read, now_utc_iso

#: Predicado de identidad dual. Parámetros: ``(user_id, user_key, user_id)``;
#: con ``user_id=None`` se reduce a ``user_key = %s``. El razonamiento está en
#: ``db/repositories/watchlist.py``. Interpolarlo con f-string no es inyección
#: (por eso el ``S608`` de este fichero está desactivado en ``pyproject.toml``):
#: es una constante del módulo, y los valores viajan siempre como ``%s``.
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


#: Filtro de lectura de «Ver todas» en la campana. Cerrado: el predicado SQL de
#: cada valor está escrito aquí y no se compone desde lo que llega por la query.
EstadoLectura = Literal["todas", "sin_leer", "leidas"]

_PREDICADO_LECTURA: dict[str, str] = {
    "todas": "",
    "sin_leer": " AND n.read_at IS NULL",
    "leidas": " AND n.read_at IS NOT NULL",
}

#: Predicado de identidad dual con el alias de ``user_notifications``.
_IDENT_N = "(n.user_id = %s OR (n.user_key = %s AND (n.user_id IS NULL OR %s::int IS NULL)))"


class PaginaAlertas(TypedDict):
    """Una página de la bandeja de alertas de una persona en una organización."""

    items: list[dict[str, Any]]
    #: Cuántas alertas cumplen el filtro, no cuántas trae la página.
    total: int
    #: Las no leídas, sea cual sea el filtro: es el número del distintivo de la
    #: campana, y no puede bajar porque alguien mire solo las leídas.
    sin_leer: int


def listar_alertas(
    user_key: str,
    organization_id: int,
    *,
    user_id: int | None = None,
    estado: EstadoLectura = "todas",
    limit: int = 20,
    offset: int = 0,
) -> PaginaAlertas:
    """La bandeja completa de la campana, paginada y con filtro de lectura.

    Es lo que el canal ``in_app`` del outbox (``scheduler/jobs/event_dispatch``)
    y los productores directos (reglas, plazos) dejaron para esta persona en
    esta organización: lo suyo, no el mercado.

    El orden es **cronológico** (lo más reciente arriba, ``id`` como
    desempate) y no «sin leer primero» como la vista previa antigua: con
    paginación por desplazamiento, un orden que dependa de ``read_at`` movería
    de página la alerta que alguien acaba de abrir y la página siguiente
    saltaría una. Lo nuevo entra por arriba; lo leído se queda donde estaba.

    ``organization_id`` es obligatorio: una lectura sin ámbito mezclaría las
    bandejas de todas las organizaciones de la persona, y la campana trabaja
    sobre la organización activa, como el resto de la consola.

    ``pursuit_id`` llega resuelto igual que en
    ``services.notifications.get_user_alerts``: si el expediente ya es una
    oportunidad de la organización, la campana enlaza a su ficha.
    """
    filtro = _PREDICADO_LECTURA[estado]
    ident = (user_id, user_key, user_id)
    with connect_read() as c:
        cur = c.execute(
            "SELECT n.id, n.created_at, n.type, n.title, n.body, n.licitacion_id, "
            "n.rule_id, n.read_at, p.id AS pursuit_id "
            "FROM user_notifications n "
            "LEFT JOIN pursuits p ON p.organization_id = n.organization_id "
            "AND p.licitacion_id = n.licitacion_id "
            f"WHERE {_IDENT_N} AND n.organization_id = %s{filtro} "
            "ORDER BY n.created_at DESC, n.id DESC LIMIT %s OFFSET %s",
            (*ident, organization_id, limit, offset),
        )
        cols = [d[0] for d in cur.description]
        items = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        # Los dos recuentos en una sola consulta: ``FILTER`` ahorra el segundo
        # viaje que pediría el número del distintivo.
        fila = c.execute(
            f"SELECT COUNT(*) FILTER (WHERE TRUE{filtro}), "
            "COUNT(*) FILTER (WHERE n.read_at IS NULL) "
            f"FROM user_notifications n WHERE {_IDENT_N} AND n.organization_id = %s",
            (*ident, organization_id),
        ).fetchone()
    total, sin_leer = (int(fila[0]), int(fila[1])) if fila else (0, 0)
    return PaginaAlertas(items=items, total=total, sin_leer=sin_leer)


# ---------------------------------------------------------------------------
# Alertas in-app de la campana y preferencias de correo
#
# Vivían en ``services/notifications.py`` con ``connect``/``connect_read``
# importados en el servicio (whitelist TID251) y diez ``noqa: S608``. ADR-022:
# el SQL vive en ``db/``; el servicio conserva lo que es regla —el modo por
# defecto de cada evento, la validación contra el catálogo y el fail-safe de la
# lectura—. El comportamiento es el mismo, sentencia a sentencia.
# ---------------------------------------------------------------------------


def alertas_de_usuario(
    user_key: str,
    limit: int = 50,
    organization_id: int | None = None,
    *,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Alertas de reglas/plazos, las no leídas primero y luego por fecha.

    ``pursuit_id`` sale de un ``LEFT JOIN`` por ``(organization_id,
    licitacion_id)``: ver ``services.notifications.get_user_alerts``.
    """
    select = (
        "SELECT n.id, n.created_at, n.type, n.title, n.body, n.licitacion_id, "
        "n.rule_id, n.read_at, p.id AS pursuit_id "
        "FROM user_notifications n "
        "LEFT JOIN pursuits p ON p.organization_id = n.organization_id "
        "AND p.licitacion_id = n.licitacion_id "
    )
    with connect_read() as c:
        if organization_id is None:
            cur = c.execute(
                select + f"WHERE {_IDENT_N} "
                "ORDER BY n.read_at IS NOT NULL, n.created_at DESC "
                "LIMIT %s",
                (user_id, user_key, user_id, limit),
            )
        else:
            cur = c.execute(
                select + f"WHERE {_IDENT_N} AND n.organization_id = %s "
                "ORDER BY n.read_at IS NOT NULL, n.created_at DESC "
                "LIMIT %s",
                (user_id, user_key, user_id, organization_id, limit),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def contar_alertas_sin_leer(
    user_key: str, organization_id: int | None = None, *, user_id: int | None = None
) -> int:
    """Número de alertas no leídas del usuario (en la organización, si se da)."""
    with connect_read() as c:
        if organization_id is None:
            row = c.execute(
                f"SELECT COUNT(*) FROM user_notifications WHERE {_IDENT} AND read_at IS NULL",
                (user_id, user_key, user_id),
            ).fetchone()
        else:
            row = c.execute(
                f"SELECT COUNT(*) FROM user_notifications WHERE {_IDENT} "
                "AND organization_id = %s AND read_at IS NULL",
                (user_id, user_key, user_id, organization_id),
            ).fetchone()
    return int(row[0]) if row else 0


def marcar_alertas_leidas(
    user_key: str,
    alert_ids: list[int],
    organization_id: int | None = None,
    *,
    user_id: int | None = None,
) -> None:
    """Marca como leídas las alertas indicadas que sigan sin leer."""
    if not alert_ids:
        return
    now_ts = datetime.now(UTC).isoformat()
    # Un ``%s`` por id: lo único que se interpola es el número de marcadores.
    placeholders = ",".join(["%s"] * len(alert_ids))
    with connect() as c:
        if organization_id is None:
            c.execute(
                f"UPDATE user_notifications SET read_at = %s WHERE {_IDENT} "
                f"AND id IN ({placeholders}) AND read_at IS NULL",
                [now_ts, user_id, user_key, user_id, *alert_ids],
            )
        else:
            c.execute(
                f"UPDATE user_notifications SET read_at = %s WHERE {_IDENT} "
                f"AND organization_id = %s AND id IN ({placeholders}) AND read_at IS NULL",
                [now_ts, user_id, user_key, user_id, organization_id, *alert_ids],
            )


def marcar_todas_alertas_leidas(
    user_key: str, organization_id: int | None = None, *, user_id: int | None = None
) -> None:
    """Marca como leídas todas las alertas pendientes del usuario."""
    now_ts = datetime.now(UTC).isoformat()
    with connect() as c:
        if organization_id is None:
            c.execute(
                f"UPDATE user_notifications SET read_at = %s WHERE {_IDENT} AND read_at IS NULL",
                (now_ts, user_id, user_key, user_id),
            )
        else:
            c.execute(
                f"UPDATE user_notifications SET read_at = %s WHERE {_IDENT} "
                "AND organization_id = %s AND read_at IS NULL",
                (now_ts, user_id, user_key, user_id, organization_id),
            )


def borrar_alertas_de_usuario(user_key: str, *, user_id: int | None = None) -> int:
    """Borra todas las alertas in-app del usuario (GDPR). Filas borradas."""
    with connect() as c:
        cur = c.execute(
            f"DELETE FROM user_notifications WHERE {_IDENT}",
            (user_id, user_key, user_id),
        )
        return int(cur.rowcount)


def leer_modo_email(user_key: str, event_type: str, *, user_id: int | None = None) -> str | None:
    """El ``modo`` guardado para ese usuario y evento, o ``None`` si no hay fila.

    Con identidad dual pueden convivir dos filas (la de la clave actual y la de
    un correo anterior): gana la de la clave actual y, entre iguales, la más
    reciente. No captura errores: el fail-safe hacia el modo por defecto es
    regla del servicio (``services.notifications.modo_email_de``).
    """
    with connect_read() as c:
        row = c.execute(
            f"SELECT modo FROM user_event_prefs WHERE {_IDENT} AND event_type = %s "
            "ORDER BY CASE WHEN user_key = %s THEN 0 ELSE 1 END, updated_at DESC LIMIT 1",
            (user_id, user_key, user_id, event_type, user_key),
        ).fetchone()
    if row is None:
        return None
    return None if row[0] is None else str(row[0])


def guardar_modo_email(
    user_key: str, event_type: str, modo: str, *, user_id: int | None = None
) -> None:
    """Escribe la preferencia de correo; el modo llega ya validado.

    La fila se localiza primero por identidad dual (v129): tras un cambio de
    correo vive bajo la clave antigua y ``ON CONFLICT(user_key, event_type)`` a
    secas guardaría una segunda preferencia en vez de cambiar la que hay. Solo
    si no hay ninguna se inserta.
    """
    now = now_utc_iso()
    with connect() as c:
        cur = c.execute(
            "UPDATE user_event_prefs SET modo = %s, updated_at = %s, "
            f"user_id = COALESCE(user_id, %s) WHERE {_IDENT} AND event_type = %s",
            (modo, now, user_id, user_id, user_key, user_id, event_type),
        )
        if int(getattr(cur, "rowcount", 0) or 0) > 0:
            return
        c.execute(
            "INSERT INTO user_event_prefs (user_key, user_id, event_type, modo, updated_at) "
            "VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT(user_key, event_type) DO UPDATE SET "
            "modo = excluded.modo, updated_at = excluded.updated_at, "
            "user_id = COALESCE(user_event_prefs.user_id, excluded.user_id)",
            (user_key, user_id, event_type, modo, now),
        )


def borrar_preferencias_email(user_key: str, *, user_id: int | None = None) -> int:
    """Borra las preferencias de correo del usuario (GDPR). Filas borradas."""
    with connect() as c:
        cur = c.execute(
            f"DELETE FROM user_event_prefs WHERE {_IDENT}",
            (user_id, user_key, user_id),
        )
        return int(cur.rowcount)
