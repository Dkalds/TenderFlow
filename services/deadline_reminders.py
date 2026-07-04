"""Recordatorios de vencimiento para favoritos del usuario (Feature D).

Genera notificaciones in-app (y opcionalmente email via pending_digests)
para licitaciones favoritas del usuario cuyo plazo (fecha_limite) o
fin de contrato (fecha_fin) se aproxima.

Ventanas: 30 dias, 7 dias, 1 dia.
El tipo de notificacion incluye la ventana para garantizar el UNIQUE
(user_key, licitacion_id, type) y evitar duplicados entre runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from db.database import connect, connect_read
from observability.logging import get_logger

log = get_logger(__name__)

# Ventanas de alerta en dias
_DEADLINE_WINDOWS = [30, 7, 1]


def _get_watchlist_items(user_key: str) -> list[str]:
    """Devuelve los id_externo de los favoritos del usuario."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT id_externo FROM watchlist_items WHERE user_key = ?",
            (user_key,),
        )
        return [str(row[0]) for row in cur.fetchall()]


def _get_licitaciones_for_deadlines(
    ids: list[str],
) -> list[dict[str, Any]]:
    """Carga titulo, fecha_limite y fecha_fin de las licitaciones favoritas."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with connect_read() as c:
        cur = c.execute(
            f"SELECT id_externo, titulo, fecha_limite, fecha_fin "  # noqa: S608
            f"FROM licitaciones WHERE id_externo IN ({placeholders})",
            ids,
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _deadline_type(days_left: int, field: str) -> str:
    """Genera el tipo de notificacion segun la ventana y el campo."""
    prefix = "renovacion" if field == "fecha_fin" else "deadline"
    return f"{prefix}_{days_left}"


def check_deadlines_and_notify(user_key: str) -> int:
    """Genera notificaciones de deadline para los favoritos del usuario.

    Idempotente: INSERT OR IGNORE en user_notifications (UNIQUE por user_key, licitacion_id, type).

    Returns:
        Numero de notificaciones nuevas escritas.
    """
    fav_ids = _get_watchlist_items(user_key)
    if not fav_ids:
        return 0

    lics = _get_licitaciones_for_deadlines(fav_ids)
    now = datetime.now(UTC)
    now_ts = now.isoformat()
    written = 0

    for lic in lics:
        lic_id = str(lic.get("id_externo") or "")
        titulo = str(lic.get("titulo") or lic_id)

        for field in ("fecha_limite", "fecha_fin"):
            raw_date = lic.get(field)
            if not raw_date:
                continue
            try:
                dt = datetime.fromisoformat(str(raw_date))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                continue

            days_left = (dt - now).days
            if days_left < 0:
                continue  # ya vencida

            for window in _DEADLINE_WINDOWS:
                if days_left > window:
                    continue
                notif_type = _deadline_type(window, field)
                label = "presentacion" if field == "fecha_limite" else "fin de contrato"
                title = f"Plazo de {label} en {days_left} dia(s): {titulo[:80]}"
                body = (
                    f"La licitacion '{titulo}' vence el {dt.date().isoformat()} ({days_left} dias)."
                )
                with connect() as c:
                    cur = c.execute(
                        "INSERT OR IGNORE INTO user_notifications "
                        "(user_key, created_at, type, title, body, licitacion_id) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (user_key, now_ts, notif_type, title, body, lic_id),
                    )
                    written += cur.rowcount

    if written:
        log.info("deadline_notifications_written", user_key=user_key[:8], count=written)
    return written


def check_all_users_deadlines() -> int:
    """Corre el check de deadlines para todos los usuarios con favoritos.

    Llamado desde el job de alertas (scheduler).
    Returns: total de notificaciones escritas.
    """
    with connect_read() as c:
        cur = c.execute("SELECT DISTINCT user_key FROM watchlist_items")
        user_keys = [row[0] for row in cur.fetchall()]

    total = 0
    for user_key in user_keys:
        try:
            total += check_deadlines_and_notify(str(user_key))
        except Exception as exc:
            log.warning("deadline_check_error", user_key=str(user_key)[:8], error=str(exc))
    return total
