"""Servicio de notificaciones -- wrapper sobre db.notifications + user_notifications.

ADR-013 / seccion 3.8: los modulos de servicios nunca importan db.* directamente.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from db.database import connect, connect_read
from db.notifications import get_unread_ids as _get_unread_ids
from db.notifications import mark_all_read as _mark_all_read
from db.notifications import mark_read as _mark_read


def mark_read(user_key: str, notification_id: str) -> None:
    """Marca una notificacion de novedad como leida."""
    _mark_read(user_key, notification_id)


def mark_all_read(user_key: str, notification_ids: list[str]) -> None:
    """Marca un batch de notificaciones de novedad como leidas."""
    _mark_all_read(user_key, notification_ids)


def get_unread_ids(user_key: str, candidate_ids: list[str]) -> list[str]:
    """Devuelve IDs de novedades que el usuario NO ha leido."""
    return _get_unread_ids(user_key, candidate_ids)


# ---------------------------------------------------------------------------
# Alertas in-app (user_notifications -- Feature A)
# ---------------------------------------------------------------------------


def get_user_alerts(
    user_key: str, limit: int = 50, organization_id: int | None = None
) -> list[dict[str, Any]]:
    """Devuelve alertas de reglas/deadlines pendientes (unread primero).

    ``pursuit_id`` llega resuelto por ``(organization_id, licitacion_id)``: si
    el expediente de la alerta ya es una oportunidad de esa organización, la
    campana enlaza a la ficha de la oportunidad y no al inspector genérico. Es
    un ``LEFT JOIN`` a propósito —una alerta de regla sobre un expediente sin
    pursuit sigue siendo válida— y cuesta un índice de PK, nada más.
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
                select + "WHERE n.user_key = %s "
                "ORDER BY n.read_at IS NOT NULL, n.created_at DESC "
                "LIMIT %s",
                (user_key, limit),
            )
        else:
            cur = c.execute(
                select + "WHERE n.user_key = %s AND n.organization_id = %s "
                "ORDER BY n.read_at IS NOT NULL, n.created_at DESC "
                "LIMIT %s",
                (user_key, organization_id, limit),
            )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def get_alerts_unread_count(user_key: str, organization_id: int | None = None) -> int:
    """Numero de alertas no leidas para el usuario."""
    with connect_read() as c:
        if organization_id is None:
            row = c.execute(
                "SELECT COUNT(*) FROM user_notifications WHERE user_key = %s AND read_at IS NULL",
                (user_key,),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT COUNT(*) FROM user_notifications WHERE user_key = %s "
                "AND organization_id = %s AND read_at IS NULL",
                (user_key, organization_id),
            ).fetchone()
    return int(row[0]) if row else 0


def mark_alerts_read(
    user_key: str, alert_ids: list[int], organization_id: int | None = None
) -> None:
    """Marca alertas especificas como leidas."""
    if not alert_ids:
        return
    now_ts = datetime.now(UTC).isoformat()
    placeholders = ",".join(["%s"] * len(alert_ids))
    with connect() as c:
        if organization_id is None:
            c.execute(
                f"UPDATE user_notifications SET read_at = %s "  # noqa: S608
                f"WHERE user_key = %s "
                f"AND id IN ({placeholders}) AND read_at IS NULL",
                [now_ts, user_key, *alert_ids],
            )
        else:
            c.execute(
                f"UPDATE user_notifications SET read_at = %s "  # noqa: S608
                f"WHERE user_key = %s AND organization_id = %s "
                f"AND id IN ({placeholders}) AND read_at IS NULL",
                [now_ts, user_key, organization_id, *alert_ids],
            )


def mark_all_alerts_read(user_key: str, organization_id: int | None = None) -> None:
    """Marca todas las alertas del usuario como leidas."""
    now_ts = datetime.now(UTC).isoformat()
    with connect() as c:
        if organization_id is None:
            c.execute(
                "UPDATE user_notifications SET read_at = %s WHERE user_key = %s AND read_at IS NULL",
                (now_ts, user_key),
            )
        else:
            c.execute(
                "UPDATE user_notifications SET read_at = %s WHERE user_key = %s "
                "AND organization_id = %s AND read_at IS NULL",
                (now_ts, user_key, organization_id),
            )


def delete_all_alerts(user_key: str) -> int:
    """Borra todas las alertas in-app del usuario (GDPR). Devuelve filas borradas."""
    with connect() as c:
        cur = c.execute("DELETE FROM user_notifications WHERE user_key = %s", (user_key,))
        return int(cur.rowcount)
