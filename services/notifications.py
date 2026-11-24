"""Servicio de notificaciones -- wrapper sobre db.notifications + user_notifications.

ADR-022: todo el SQL (lecturas de novedades, alertas in-app y preferencias de
correo) vive en ``db/notifications.py``. Aquí queda la regla: el modo de correo
por defecto de cada evento y el fail-safe de la lectura de preferencias.

Desde S4.6 del plan 2026-09 v2 este modulo lee ademas la **preferencia de
correo por usuario y tipo de evento** (``immediate | daily | off``), que es lo
que consulta el despachador antes de mandar un aviso de asignacion o de
comentario. Ninguna pantalla ni ruta la escribe: el escritor
(``set_modo_email``) se retiró sin llamadores el 2026-11-16 y la tabla
``user_event_prefs`` sigue en el esquema, vacía, así que hoy manda siempre el
modo por defecto. Quitar la tabla es una migración aparte; darle una pantalla,
volver a escribir la fila.

Desde v129 (ADR-030 fase 2) ``user_notifications`` y ``user_event_prefs``
llevan ``user_id`` además de la clave legada. Aquí todo se pide por
``user_id``: la clave de las filas sin id la resuelve ``db/notifications.py``
en la base. El borrado GDPR, que aún borra por clave lo que no tiene id, llama
a ``db/notifications.py`` directamente desde ``services/gdpr.py``.
"""

from __future__ import annotations

from typing import Any, Literal

from db.notifications import alertas_de_usuario as _alertas_de_usuario
from db.notifications import contar_alertas_sin_leer as _contar_alertas_sin_leer
from db.notifications import get_unread_ids as _get_unread_ids
from db.notifications import leer_modo_email as _leer_modo_email
from db.notifications import marcar_alertas_leidas as _marcar_alertas_leidas
from db.notifications import marcar_todas_alertas_leidas as _marcar_todas_alertas_leidas
from db.notifications import mark_all_read as _mark_all_read
from db.notifications import mark_read as _mark_read
from observability.logging import get_logger

log = get_logger(__name__)


def mark_read(notification_id: str, *, user_id: int) -> None:
    """Marca una notificacion de novedad como leida."""
    _mark_read(notification_id, user_id=user_id)


def mark_all_read(notification_ids: list[str], *, user_id: int) -> None:
    """Marca un batch de notificaciones de novedad como leidas."""
    _mark_all_read(notification_ids, user_id=user_id)


def get_unread_ids(candidate_ids: list[str], *, user_id: int) -> list[str]:
    """Devuelve IDs de novedades que el usuario NO ha leido."""
    return _get_unread_ids(candidate_ids, user_id=user_id)


# ---------------------------------------------------------------------------
# Alertas in-app (user_notifications -- Feature A)
# ---------------------------------------------------------------------------


def get_user_alerts(
    limit: int = 50,
    organization_id: int | None = None,
    *,
    user_id: int,
) -> list[dict[str, Any]]:
    """Devuelve alertas de reglas/deadlines pendientes (unread primero).

    ``pursuit_id`` llega resuelto por ``(organization_id, licitacion_id)``: si
    el expediente de la alerta ya es una oportunidad de esa organización, la
    campana enlaza a la ficha de la oportunidad y no al inspector genérico.
    Sin pursuit sale ``None`` —una alerta de regla sobre un expediente sin
    pursuit sigue siendo válida— y con varios (uno por lote) sale uno solo.
    """
    return _alertas_de_usuario(limit, organization_id, user_id=user_id)


def get_alerts_unread_count(organization_id: int | None = None, *, user_id: int) -> int:
    """Numero de alertas no leidas para el usuario."""
    return _contar_alertas_sin_leer(organization_id, user_id=user_id)


def mark_alerts_read(
    alert_ids: list[int],
    organization_id: int | None = None,
    *,
    user_id: int,
) -> None:
    """Marca alertas especificas como leidas."""
    _marcar_alertas_leidas(alert_ids, organization_id, user_id=user_id)


def mark_all_alerts_read(organization_id: int | None = None, *, user_id: int) -> None:
    """Marca todas las alertas del usuario como leidas."""
    _marcar_todas_alertas_leidas(organization_id, user_id=user_id)


# ---------------------------------------------------------------------------
# Preferencia de correo por usuario y tipo de evento (S4.6)
# ---------------------------------------------------------------------------

ModoEmail = Literal["immediate", "daily", "off"]

#: Qué se hace cuando el usuario no ha elegido nada.
#:
#: ``immediate`` para la asignación y ``daily`` para los comentarios, y la
#: asimetría es deliberada: que te asignen una oportunidad es una acción
#: pendiente con fecha límite, y un comentario es contexto. El correo por
#: comentario que llega al instante es el que hace que la gente desactive
#: TODOS los avisos del producto.
_MODO_POR_DEFECTO: dict[str, ModoEmail] = {
    "pursuit.assigned": "immediate",
    "pursuit.commented": "daily",
}


def _modo_por_defecto(event_type: str) -> ModoEmail:
    return _MODO_POR_DEFECTO.get(event_type, "daily")


def _normalizar_modo(valor: object) -> ModoEmail | None:
    """Literal válido a partir de lo que traiga la columna, o ``None``."""
    if valor == "immediate":
        return "immediate"
    if valor == "daily":
        return "daily"
    if valor == "off":
        return "off"
    return None


def modo_email_de(event_type: str, *, user_id: int | None) -> ModoEmail:
    """Cómo quiere este usuario recibir por correo este tipo de evento.

    Sin ``user_id`` no hay fila que leer (la tabla no tiene escritor desde el
    2026-11-16): manda el defecto.

    Fail-safe hacia el defecto y no hacia ``off``: si la tabla no está (base a
    medio migrar) el aviso sale igual. Silenciar por un fallo de lectura sería
    el peor modo de fallo posible — nadie se entera de que no se entera.
    """
    if user_id is None:
        return _modo_por_defecto(event_type)
    try:
        guardado = _leer_modo_email(event_type, user_id=user_id)
    except Exception:
        log.warning("user_event_prefs_lectura_fallida", event_type=event_type, exc_info=True)
        return _modo_por_defecto(event_type)
    return _normalizar_modo(guardado) or _modo_por_defecto(event_type)
