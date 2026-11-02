"""Servicio GDPR — exportación, anonimización y gestión de datos de usuario.

Centraliza las queries que usa ``api/routes/me.py`` para cumplir con el
derecho de portabilidad y el derecho al olvido (RGPD Art. 17/20).

Identidad (F13·C3.2, plan Pliegos+RAG): las funciones ``export_watchlist*``/
``anonymize_user_data`` reciben ``user_key`` — la misma clave opaca
``sha256(email o key_hash)[:16]`` que ya usan ``watchlist_rules``/
``watchlist_items``/``competitive``/``user_profiles`` (ver ``_user_key`` en
``api/routes/me.py``), NO el ``key_hash`` crudo de la API key. Antes de este
cambio, ``me.py`` pasaba el ``key_hash`` crudo a estas mismas funciones —
como las filas de esas tablas se escriben con el hash derivado, la
exportación/borrado de watchlist nunca encontraba nada para usuarios
autenticados por API key (bug preexistente, ver test histórico
``test_export_watchlist_returns_empty_gracefully``).

Desde v129 (ADR-030 fase 2) cada función acepta además ``user_id``: el export
y el borrado cubren las filas por **id o por clave**, de modo que lo guardado
bajo el correo anterior de la persona no se queda fuera del export ni
sobrevive al borrado. Sin ``user_id`` se comportan como antes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from db import radar_dismissals
from db.repositories.api_keys import ApiKeyRepository
from db.repositories.audit import AuditRepository
from db.repositories.feedback import FeedbackRepository
from db.repositories.organizations import OrganizationRepository
from db.repositories.pursuit_comments import PursuitCommentRepository
from db.repositories.pursuit_tasks import PursuitTasksRepository
from db.repositories.pursuits import PursuitRepository
from db.repositories.user_profiles import delete_user_profile, get_own_user_profile
from db.repositories.watchlist import WatchlistRepository
from db.totp import delete_totp
from observability.logging import get_logger

log = get_logger(__name__)

_api_key_repo = ApiKeyRepository()
_watchlist_repo = WatchlistRepository()
_feedback_repo = FeedbackRepository()
_audit_repo = AuditRepository()
_organization_repo = OrganizationRepository()
_pursuit_repo = PursuitRepository()
_pursuit_comment_repo = PursuitCommentRepository()
_pursuit_task_repo = PursuitTasksRepository()

#: Filas máximas por sección del export (el ``LIMIT`` de cada consulta). Una
#: sección que llega al tope puede estar truncada: ``GET /me/data`` lo declara en
#: ``metadata.json`` en vez de entregar un export que parece completo y no lo es.
EXPORT_TOPES: dict[str, int] = {
    "audit": 1000,
    "follows": 5000,
    "notificaciones": 5000,
    "pursuits": 5000,
    "pursuit_events": 5000,
    "pursuit_comments": 5000,
    "pursuit_tasks": 5000,
    "accesos": 5000,
    "asistente_feedback": 5000,
}


def get_user_id_from_key_id(key_id: int) -> int | None:
    """Obtiene el ``user_id`` vinculado a la API key, si la columna existe.

    Returns ``None`` (never an arbitrary user) when the column is missing
    or the value is NULL.  See issue #44.
    """
    result = _api_key_repo.get_user_id(key_id)
    if result is None:
        log.warning(
            "gdpr_user_id_null_or_missing",
            key_id=key_id,
            msg="user_id is NULL, column missing, or key not found",
        )
    return result


def export_watchlist(key_hash: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Exporta las entradas de watchlist del usuario."""
    return _watchlist_repo.export_by_user_key(key_hash, user_id)


def export_watchlist_items(key_hash: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Exporta los favoritos de licitaciones (watchlist_items) del usuario."""
    return _watchlist_repo.export_items_by_user_key(key_hash, user_id)


def export_follows(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Exporta los seguimientos unificados (``follows``) del usuario."""
    from db.repositories import follows

    return follows.exportar_de_usuario(user_key, user_id=user_id)


def export_watchlist_rules(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Exporta las reglas de watchlist por criterio (mi-watchlist) del usuario."""
    from services.watchlist_rules import list_rules

    return [r.model_dump() for r in list_rules(user_key, user_id=user_id)]


def export_saved_filters(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Exporta las vistas guardadas del usuario (todas, sin ámbito de equipo)."""
    from db.saved_filters import list_own_saved_filters

    return list_own_saved_filters(user_key, user_id=user_id)


def export_user_profile(user_key: str, *, user_id: int | None = None) -> dict[str, Any] | None:
    """Exporta el perfil de scoring personalizado del usuario, si existe."""
    # Export GDPR: la pregunta es qué guarda el sistema sobre esta persona,
    # no qué ve un equipo. Camino sin ámbito, pedido por su nombre.
    return get_own_user_profile(user_key, user_id=user_id)


def export_user_notifications(user_key: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Exporta las alertas in-app (user_notifications) del usuario."""
    from services.notifications import get_user_alerts

    return get_user_alerts(user_key, limit=5000, user_id=user_id)


def export_feedback(user_id: int) -> list[dict[str, Any]]:
    """Exporta todo el ML feedback (anónimo, sin FK a usuario)."""
    return _feedback_repo.export_for_user(user_id)


def export_audit_log(key_hash: str, *, user_id: int | None = None) -> list[dict[str, Any]]:
    """Exporta el audit log filtrado por ``user_key`` (y ``user_id`` si se conoce)."""
    return _audit_repo.export_by_user_key(key_hash, user_id)


def export_collaboration_data(user_id: int) -> dict[str, list[dict[str, object]]]:
    """Exporta membresías y filas corporativas vinculadas personalmente.

    No vuelca oportunidades de compañeros sin relación personal con el
    solicitante: la portabilidad GDPR no debe convertirse en una exportación
    indiscriminada de información corporativa.
    """
    data = _pursuit_repo.export_personal_data(user_id)
    return {
        "organization_memberships": _organization_repo.export_memberships_for_user(user_id),
        **data,
        # Solo lo que escribió el solicitante: los comentarios de sus compañeros
        # en el mismo hilo son datos de ellos, no suyos.
        "pursuit_comments": _pursuit_comment_repo.export_for_user(user_id),
    }


def secciones_truncadas(secciones: Mapping[str, Sequence[object]]) -> dict[str, int]:
    """Secciones del export que alcanzaron su tope (:data:`EXPORT_TOPES`), con el tope."""
    return {
        nombre: EXPORT_TOPES[nombre]
        for nombre, filas in secciones.items()
        if nombre in EXPORT_TOPES and len(filas) >= EXPORT_TOPES[nombre]
    }


def export_account_data(user_id: int, user_key: str) -> dict[str, list[dict[str, object]]]:
    """Lo que se guarda de la cuenta y no cubre ningún otro export (RGPD Art. 15/20).

    La fila de ``users`` (sin credenciales), los accesos, las sesiones activas
    (con el id público, nunca el hash), las preferencias de notificación, los
    descartes vigentes del Radar, los votos del asistente y las tareas asignadas:
    todo lo que el borrado ya alcanza y el export omitía. Las claves son nombres
    de fichero del ZIP.
    """
    from db import sessions, users
    from db.repositories import asistente_feedback, notification_preferences

    return {
        "cuenta": users.export_account(user_id),
        "accesos": users.export_access_log(user_id),
        "sesiones": [
            {
                "id": sessions.session_public_id(str(fila["token_hash"])),
                **{k: v for k, v in fila.items() if k != "token_hash"},
            }
            for fila in sessions.list_active_sessions(user_id)
        ],
        "preferencias_notificacion": notification_preferences.listar(user_id),
        "descartes_radar": radar_dismissals.list_detalle(user_key, user_id=user_id),
        "asistente_feedback": asistente_feedback.exportar_de_usuario(user_id),
        "pursuit_tasks": _pursuit_task_repo.export_for_user(user_id),
    }


def organizaciones_con_unico_owner(user_id: int) -> list[int]:
    """Organizaciones compartidas que quedarían sin owner si esta cuenta se borra."""
    return _organization_repo.organizaciones_con_unico_owner(user_id)


def anonymize_account(user_id: int, email: str | None) -> None:
    """Derecho al olvido de una cuenta ejecutado por un administrador (RGPD Art. 17).

    La misma cadena que ``DELETE /me`` (``api.routes.me.delete_my_data``): primero
    los datos personales, las membresías y las invitaciones —que se localizan por
    el correo— y solo después ``users``, cuya anonimización borra ese correo y la
    clave que se deriva de él. Antes la acción del panel solo llamaba a
    ``anonymize_user`` y dejaba watchlist, reglas, perfil, vistas, alertas,
    seguimientos, membresías, invitaciones y credenciales.

    No revoca sesiones ni API keys: eso lo hace quien llama.
    """
    from db.users import anonymize_user
    from shared.identity import user_key_from_email

    anonymize_user_data(user_key_from_email(email, user_id), user_id=user_id)
    anonymize_user(user_id)


def anonymize_user_data(
    user_key: str, key_id: int | None = None, *, user_id: int | None = None
) -> None:
    """Anonimiza/borra los datos personales del usuario (RGPD Art. 17).

    Cubre watchlist (empresa/CPV), favoritos, reglas de watchlist por criterio,
    perfil de scoring, alertas in-app y sus marcas de lectura, descartes del Radar, seguimientos
    (``follows``), votos del asistente, preferencias de notificación y de
    correo, el segundo factor (TOTP), las tareas asignadas y el nombre de la
    organización personal — todo lo persistido bajo ``user_key`` **o** ``user_id`` (v129: un
    borrado que sólo mirase la clave del correo actual dejaría vivo lo
    guardado con el anterior). Si se pasa ``key_id`` (autenticación por API
    key), además revoca esa key.
    """
    from db.repositories import asistente_feedback, follows, notification_preferences
    from db.saved_filters import delete_all_for_user as delete_all_saved_filters
    from services.notifications import delete_all_alerts, delete_email_prefs
    from services.watchlist_rules import delete_all_for_user

    _watchlist_repo.anonymize_by_user_key(user_key, user_id)
    _watchlist_repo.anonymize_items_by_user_key(user_key, user_id)
    delete_all_for_user(user_key, user_id=user_id)
    delete_all_saved_filters(user_key, user_id=user_id)
    delete_user_profile(user_key, user_id=user_id)
    delete_all_alerts(user_key, user_id=user_id)
    delete_email_prefs(user_key, user_id=user_id)
    radar_dismissals.delete_all_for_user(user_key, user_id=user_id)
    follows.borrar_de_usuario(user_key, user_id=user_id)
    if user_id is not None:
        _feedback_repo.delete_for_user(user_id)
        asistente_feedback.borrar_de_usuario(user_id)
        notification_preferences.borrar_de_usuario(user_id)
        _pursuit_repo.anonymize_user_references(user_id)
        _pursuit_comment_repo.anonymize_author(user_id)
        _pursuit_task_repo.anonymize_user_references(user_id)
        delete_totp(user_id)
        _organization_repo.remove_memberships_for_user(user_id)
    if key_id is not None:
        _api_key_repo.deactivate_by_id(key_id)


def revoke_all_api_keys_for_user(user_id: int) -> int:
    """Desactiva todas las API keys del usuario (borrado de cuenta por sesión)."""
    return _api_key_repo.deactivate_all_for_user(user_id)


def set_key_expiry(key_id: int, expires_at: str) -> None:
    """Establece ``expires_at`` en una API key (para rotación con grace period)."""
    _api_key_repo.set_expiry(key_id, expires_at)
