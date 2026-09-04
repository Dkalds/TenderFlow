"""Recordatorios de vencimiento para favoritos del usuario (Feature D).

Genera notificaciones in-app (y opcionalmente email via pending_digests)
para licitaciones favoritas del usuario cuyo plazo (fecha_limite) o
fin de contrato (fecha_fin) se aproxima.

Ventanas: 30 dias, 7 dias, 1 dia.
El tipo de notificacion incluye la ventana para garantizar el UNIQUE
(user_key, licitacion_id, type) y evitar duplicados entre runs.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from db.database import connect_read
from db.notifications import insert_user_notification
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from shared.identity import user_key_from_email

log = get_logger(__name__)

# Ventanas de alerta en dias
_DEADLINE_WINDOWS = [30, 7, 1]
#: Ventanas de la próxima acción de un pursuit. ``0`` es «hoy»: la acción la
#: fijó el propio equipo y el día señalado merece aviso aunque no falte nada.
_ACCION_WINDOWS = [7, 1, 0]


def _get_watchlist_items(user_key: str) -> dict[str, int]:
    """``id_externo -> organization_id`` de los favoritos del usuario.

    Devuelve un mapa y no una lista porque el recordatorio **hereda la
    organización del favorito que lo origina**. La campana lee
    ``user_notifications`` con ámbito (``services/notifications.get_user_alerts``
    y sus vecinas reciben siempre un ``organization_id`` ya resuelto desde
    ``api/tenancy.py``, nunca ``None``), así que una alerta escrita sin
    organización no aparece en ninguna parte: es la misma clase de fila
    invisible que S4.3 cerró en los repositorios de tenencia, y este job la
    seguía escribiendo con su ``INSERT`` crudo.

    Las filas legacy con ``organization_id IS NULL`` —las que se escribieron
    cuando la columna era opcional— se descartan aquí en vez de propagar el
    ``None`` hasta la escritura. Crear la alerta huérfana sería peor que no
    crearla: gasta la clave ``UNIQUE(user_key, licitacion_id, type)`` con una
    fila que el usuario no ve. Descartarlas se cura solo: en cuanto
    ``scripts/asignar_organizacion_huerfanos.py`` adjudica el favorito a la
    organización personal de su dueño, la siguiente pasada del job lo avisa.
    """
    with connect_read() as c:
        cur = c.execute(
            "SELECT id_externo, organization_id FROM watchlist_items WHERE user_key = %s",
            (user_key,),
        )
        filas = cur.fetchall()
    items = {str(row[0]): int(row[1]) for row in filas if row[1] is not None}
    descartados = len(filas) - len(items)
    if descartados:
        # Silenciarlo dejaría a un usuario sin recordatorios sin que nada lo
        # delate; el aviso nombra cuántos y a quién para poder correr el
        # backfill de tenencia.
        log.warning(
            "watchlist_items_sin_organizacion",
            user_key=user_key[:8],
            descartados=descartados,
        )
    return items


def _get_licitaciones_for_deadlines(
    ids: list[str],
) -> list[dict[str, Any]]:
    """Carga titulo, fecha_limite y fecha_fin de las licitaciones favoritas."""
    if not ids:
        return []
    placeholders = ",".join(["%s"] * len(ids))
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

    Idempotente: upsert (ON CONFLICT DO NOTHING) en user_notifications (UNIQUE por user_key, licitacion_id, type).

    La escritura pasa por :func:`db.notifications.insert_user_notification`, el
    único productor de alertas de producto, para que la alerta lleve la
    ``organization_id`` del favorito. Hasta 2026-09 este job repetía aquí su
    propio ``INSERT`` y era el único de los tres productores que no ponía la
    columna: escribía alertas correctas e invisibles.

    Returns:
        Numero de notificaciones nuevas escritas.
    """
    favoritos = _get_watchlist_items(user_key)
    if not favoritos:
        return 0

    lics = _get_licitaciones_for_deadlines(list(favoritos))
    now = datetime.now(UTC)
    now_ts = now.isoformat()
    written = 0

    for lic in lics:
        lic_id = str(lic.get("id_externo") or "")
        organization_id = favoritos.get(lic_id)
        if organization_id is None:
            # No debería ocurrir: las licitaciones salen de la propia consulta
            # de favoritos. Si ocurriera, escribir con ``None`` es justo lo que
            # este camino evita, así que se salta.
            continue
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
                written += int(
                    insert_user_notification(
                        user_key=user_key,
                        type_=notif_type,
                        title=title,
                        body=body,
                        licitacion_id=lic_id,
                        organization_id=organization_id,
                        created_at=now_ts,
                    )
                )

    if written:
        log.info("deadline_notifications_written", user_key=user_key[:8], count=written)
    return written


def _dias_hasta(raw: object, hoy: date) -> int | None:
    """Días naturales hasta una fecha ISO (o datetime ISO); ``None`` si no parsea."""
    try:
        return (date.fromisoformat(str(raw)[:10]) - hoy).days
    except (ValueError, TypeError):
        return None


def check_pursuit_deadlines() -> int:
    """Recordatorios para los pursuits abiertos con responsable.

    Dos fechas por pursuit: el plazo de presentación del expediente, con las
    mismas ventanas y el mismo ``type`` que los favoritos (``deadline_<n>``,
    así quien además lo tiene en favoritos no recibe el aviso dos veces), y la
    próxima acción que el equipo se fijó (``accion_<n>``, con ventana «hoy»).

    Hasta 2026-09 el pursuit —el objeto con compromisos de verdad— no generaba
    ningún recordatorio: sólo la watchlist lo hacía, y ni siquiera ella corría
    en producción porque nada llamaba a :func:`check_all_users_deadlines`.
    """
    rows = PursuitRepository().deadline_rows()
    hoy = datetime.now(UTC).date()
    written = 0
    for row in rows:
        email = row.get("responsible_email")
        responsable = row.get("responsible_user_id")
        if not email or responsable is None:
            continue
        user_key = user_key_from_email(str(email), int(responsable))
        lic_id = str(row["licitacion_id"])
        titulo = str(row.get("titulo") or lic_id)
        organization_id = int(row["organization_id"])

        dias = _dias_hasta(row.get("fecha_limite"), hoy)
        if dias is not None and dias >= 0:
            for window in _DEADLINE_WINDOWS:
                if dias > window:
                    continue
                written += int(
                    insert_user_notification(
                        user_key=user_key,
                        type_=_deadline_type(window, "fecha_limite"),
                        title=f"Plazo de presentacion en {dias} dia(s): {titulo[:80]}",
                        body=f"La oportunidad '{titulo}' vence el "
                        f"{str(row.get('fecha_limite'))[:10]} ({dias} dias).",
                        licitacion_id=lic_id,
                        organization_id=organization_id,
                    )
                )

        accion_dias = _dias_hasta(row.get("next_action_due"), hoy)
        if accion_dias is not None and accion_dias >= 0:
            accion = str(row.get("next_action") or "Próxima acción")[:80]
            cuando = "hoy" if accion_dias == 0 else f"en {accion_dias} dia(s)"
            for window in _ACCION_WINDOWS:
                if accion_dias > window:
                    continue
                written += int(
                    insert_user_notification(
                        user_key=user_key,
                        type_=f"accion_{window}",
                        title=f"Proxima accion {cuando}: {accion}",
                        body=f"Oportunidad '{titulo[:80]}'.",
                        licitacion_id=lic_id,
                        organization_id=organization_id,
                    )
                )
    if written:
        log.info("pursuit_deadline_notifications_written", count=written)
    return written


def check_all_users_deadlines() -> int:
    """Corre el check de deadlines para todos los usuarios con favoritos y
    para los pursuits abiertos.

    Llamado desde ``_run_watchlist_notify`` (pipeline canónica, cada pasada).
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
    try:
        total += check_pursuit_deadlines()
    except Exception as exc:
        log.warning("pursuit_deadline_check_error", error=str(exc)[:200])
    return total
