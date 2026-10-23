"""Servicio de notificaciones -- wrapper sobre db.notifications + user_notifications.

ADR-022: todo el SQL (lecturas de novedades, alertas in-app y preferencias de
correo) vive en ``db/notifications.py``. Aquí queda la regla: el modo de correo
por defecto de cada evento, la validación contra el catálogo y el fail-safe de
la lectura de preferencias.

Desde S4.6 del plan 2026-09 v2 este modulo guarda ademas la **preferencia de
correo por usuario y tipo de evento** (``immediate | daily | off``), que es lo
que consulta el despachador antes de mandar un aviso de asignacion o de
comentario. Vive aqui y no en el despachador porque es estado de usuario, no
mecanica de reparto: la misma preferencia la leera la pantalla de perfil.

Desde v129 (ADR-030 fase 2) ``user_notifications`` y ``user_event_prefs``
llevan ``user_id`` junto a ``user_key``. Todas las funciones aceptan
``user_id`` opcional: con él la lectura es dual (por id, o por clave en las
filas que el backfill no resolvió) y la escritura pone las dos columnas; sin
él se comportan exactamente como antes.
"""

from __future__ import annotations

from typing import Any, Literal

from db.notifications import alertas_de_usuario as _alertas_de_usuario
from db.notifications import borrar_alertas_de_usuario as _borrar_alertas_de_usuario
from db.notifications import borrar_preferencias_email as _borrar_preferencias_email
from db.notifications import contar_alertas_sin_leer as _contar_alertas_sin_leer
from db.notifications import get_unread_ids as _get_unread_ids
from db.notifications import guardar_modo_email as _guardar_modo_email
from db.notifications import leer_modo_email as _leer_modo_email
from db.notifications import marcar_alertas_leidas as _marcar_alertas_leidas
from db.notifications import marcar_todas_alertas_leidas as _marcar_todas_alertas_leidas
from db.notifications import mark_all_read as _mark_all_read
from db.notifications import mark_read as _mark_read
from observability.logging import get_logger
from shared.events import CATALOGO

log = get_logger(__name__)


def mark_read(user_key: str, notification_id: str, *, user_id: int | None = None) -> None:
    """Marca una notificacion de novedad como leida."""
    _mark_read(user_key, notification_id, user_id=user_id)


def mark_all_read(
    user_key: str, notification_ids: list[str], *, user_id: int | None = None
) -> None:
    """Marca un batch de notificaciones de novedad como leidas."""
    _mark_all_read(user_key, notification_ids, user_id=user_id)


def get_unread_ids(
    user_key: str, candidate_ids: list[str], *, user_id: int | None = None
) -> list[str]:
    """Devuelve IDs de novedades que el usuario NO ha leido."""
    return _get_unread_ids(user_key, candidate_ids, user_id=user_id)


# ---------------------------------------------------------------------------
# Alertas in-app (user_notifications -- Feature A)
# ---------------------------------------------------------------------------


def get_user_alerts(
    user_key: str,
    limit: int = 50,
    organization_id: int | None = None,
    *,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """Devuelve alertas de reglas/deadlines pendientes (unread primero).

    ``pursuit_id`` llega resuelto por ``(organization_id, licitacion_id)``: si
    el expediente de la alerta ya es una oportunidad de esa organización, la
    campana enlaza a la ficha de la oportunidad y no al inspector genérico. Es
    un ``LEFT JOIN`` a propósito —una alerta de regla sobre un expediente sin
    pursuit sigue siendo válida— y cuesta un índice de PK, nada más.
    """
    return _alertas_de_usuario(user_key, limit, organization_id, user_id=user_id)


def get_alerts_unread_count(
    user_key: str, organization_id: int | None = None, *, user_id: int | None = None
) -> int:
    """Numero de alertas no leidas para el usuario."""
    return _contar_alertas_sin_leer(user_key, organization_id, user_id=user_id)


def mark_alerts_read(
    user_key: str,
    alert_ids: list[int],
    organization_id: int | None = None,
    *,
    user_id: int | None = None,
) -> None:
    """Marca alertas especificas como leidas."""
    _marcar_alertas_leidas(user_key, alert_ids, organization_id, user_id=user_id)


def mark_all_alerts_read(
    user_key: str, organization_id: int | None = None, *, user_id: int | None = None
) -> None:
    """Marca todas las alertas del usuario como leidas."""
    _marcar_todas_alertas_leidas(user_key, organization_id, user_id=user_id)


def delete_all_alerts(user_key: str, *, user_id: int | None = None) -> int:
    """Borra todas las alertas in-app del usuario (GDPR). Devuelve filas borradas."""
    return _borrar_alertas_de_usuario(user_key, user_id=user_id)


# ---------------------------------------------------------------------------
# Preferencia de correo por usuario y tipo de evento (S4.6)
# ---------------------------------------------------------------------------

ModoEmail = Literal["immediate", "daily", "off"]

MODOS_EMAIL: tuple[ModoEmail, ...] = ("immediate", "daily", "off")

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


def modo_email_de(user_key: str, event_type: str, *, user_id: int | None = None) -> ModoEmail:
    """Cómo quiere este usuario recibir por correo este tipo de evento.

    Fail-safe hacia el defecto y no hacia ``off``: si la tabla no está (base a
    medio migrar) el aviso sale igual. Silenciar por un fallo de lectura sería
    el peor modo de fallo posible — nadie se entera de que no se entera.
    """
    try:
        guardado = _leer_modo_email(user_key, event_type, user_id=user_id)
    except Exception:
        log.warning("user_event_prefs_lectura_fallida", event_type=event_type, exc_info=True)
        return _modo_por_defecto(event_type)
    return _normalizar_modo(guardado) or _modo_por_defecto(event_type)


def set_modo_email(
    user_key: str, event_type: str, modo: str, *, user_id: int | None = None
) -> ModoEmail:
    """Fija la preferencia de correo del usuario para un tipo de evento.

    La fila a actualizar se localiza por identidad dual (v129): tras un cambio
    de correo vive bajo la clave antigua y ``ON CONFLICT(user_key, event_type)``
    a secas guardaría una segunda preferencia en vez de cambiar la que hay.

    Raises:
        ValueError: el tipo no admite preferencia de correo, o el modo no es
            uno de los tres. Se valida contra el catálogo y no contra una lista
            propia para que un tipo nuevo no necesite tocar esto.
    """
    spec = CATALOGO.get(event_type)
    if spec is None or not spec.preferencia_email:
        raise ValueError(f"El evento {event_type!r} no admite preferencia de correo.")
    normalizado = _normalizar_modo(modo)
    if normalizado is None:
        raise ValueError(f"Modo inválido: {modo!r}. Permitidos: {', '.join(MODOS_EMAIL)}")
    _guardar_modo_email(user_key, event_type, normalizado, user_id=user_id)
    return normalizado


def preferencias_email(user_key: str, *, user_id: int | None = None) -> dict[str, ModoEmail]:
    """Preferencia efectiva del usuario para cada tipo que admite correo."""
    return {
        tipo: modo_email_de(user_key, tipo, user_id=user_id)
        for tipo, spec in sorted(CATALOGO.items())
        if spec.preferencia_email
    }


def delete_email_prefs(user_key: str, *, user_id: int | None = None) -> int:
    """Borra las preferencias de correo del usuario (GDPR). Filas borradas."""
    return _borrar_preferencias_email(user_key, user_id=user_id)
