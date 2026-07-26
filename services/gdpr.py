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
"""

from __future__ import annotations

from typing import Any

from db.repositories.api_keys import ApiKeyRepository
from db.repositories.audit import AuditRepository
from db.repositories.feedback import FeedbackRepository
from db.repositories.user_profiles import delete_user_profile, get_user_profile
from db.repositories.watchlist import WatchlistRepository
from observability.logging import get_logger

log = get_logger(__name__)

_api_key_repo = ApiKeyRepository()
_watchlist_repo = WatchlistRepository()
_feedback_repo = FeedbackRepository()
_audit_repo = AuditRepository()


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


def export_api_keys(key_hash: str) -> list[dict[str, Any]]:
    """Exporta las API keys vinculadas al ``key_hash``."""
    return _api_key_repo.list_for_export(key_hash)


def export_watchlist(key_hash: str) -> list[dict[str, Any]]:
    """Exporta las entradas de watchlist del usuario."""
    return _watchlist_repo.export_by_user_key(key_hash)


def export_watchlist_items(key_hash: str) -> list[dict[str, Any]]:
    """Exporta los favoritos de licitaciones (watchlist_items) del usuario."""
    return _watchlist_repo.export_items_by_user_key(key_hash)


def export_watchlist_rules(user_key: str) -> list[dict[str, Any]]:
    """Exporta las reglas de watchlist por criterio (mi-watchlist) del usuario."""
    from services.watchlist_rules import list_rules

    return [r.model_dump() for r in list_rules(user_key)]


def export_user_profile(user_key: str) -> dict[str, Any] | None:
    """Exporta el perfil de scoring personalizado del usuario, si existe."""
    return get_user_profile(user_key)


def export_user_notifications(user_key: str) -> list[dict[str, Any]]:
    """Exporta las alertas in-app (user_notifications) del usuario."""
    from services.notifications import get_user_alerts

    return get_user_alerts(user_key, limit=5000)


def export_feedback(user_id: int) -> list[dict[str, Any]]:
    """Exporta todo el ML feedback (anónimo, sin FK a usuario)."""
    return _feedback_repo.export_for_user(user_id)


def export_audit_log(key_hash: str) -> list[dict[str, Any]]:
    """Exporta el audit log filtrado por ``user_key``."""
    return _audit_repo.export_by_user_key(key_hash)


def anonymize_user_data(
    user_key: str, key_id: int | None = None, *, user_id: int | None = None
) -> None:
    """Anonimiza/borra los datos personales del usuario (RGPD Art. 17).

    Cubre watchlist (empresa/CPV), favoritos, reglas de watchlist por criterio,
    perfil de scoring y alertas in-app — todo lo persistido bajo ``user_key``.
    Si se pasa ``key_id`` (autenticación por API key), además revoca esa key.
    """
    from services.notifications import delete_all_alerts
    from services.watchlist_rules import delete_all_for_user

    _watchlist_repo.anonymize_by_user_key(user_key)
    _watchlist_repo.anonymize_items_by_user_key(user_key)
    delete_all_for_user(user_key)
    delete_user_profile(user_key)
    delete_all_alerts(user_key)
    if user_id is not None:
        _feedback_repo.delete_for_user(user_id)
    if key_id is not None:
        _api_key_repo.deactivate_by_id(key_id)


def revoke_all_api_keys_for_user(user_id: int) -> int:
    """Desactiva todas las API keys del usuario (borrado de cuenta por sesión)."""
    return _api_key_repo.deactivate_all_for_user(user_id)


def list_user_keys(key_id: int) -> list[dict[str, Any]]:
    """Lista las API keys del usuario (solo la key autenticada por ID)."""
    return _api_key_repo.get_by_key_id(key_id)


def get_key_name_and_scopes(key_id: int) -> tuple[str, str] | None:
    """Obtiene nombre y scopes de una API key por ID."""
    return _api_key_repo.get_name_and_scopes(key_id)


def set_key_expiry(key_id: int, expires_at: str) -> None:
    """Establece ``expires_at`` en una API key (para rotación con grace period)."""
    _api_key_repo.set_expiry(key_id, expires_at)
