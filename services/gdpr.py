"""Servicio GDPR — exportación, anonimización y gestión de datos de usuario.

Centraliza las queries que usa ``api/routes/me.py`` para cumplir con el
derecho de portabilidad y el derecho al olvido (RGPD Art. 17/20).
"""

from __future__ import annotations

from typing import Any

from db.repositories.api_keys import ApiKeyRepository
from db.repositories.audit import AuditRepository
from db.repositories.feedback import FeedbackRepository
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


def export_feedback() -> list[dict[str, Any]]:
    """Exporta todo el ML feedback (anónimo, sin FK a usuario)."""
    return _feedback_repo.export_all()


def export_audit_log(key_hash: str) -> list[dict[str, Any]]:
    """Exporta el audit log filtrado por ``user_key``."""
    return _audit_repo.export_by_user_key(key_hash)


def anonymize_user_data(key_hash: str, key_id: int) -> None:
    """Anonimiza watchlist y revoca la API key del usuario."""
    _watchlist_repo.anonymize_by_user_key(key_hash)
    _watchlist_repo.anonymize_items_by_user_key(key_hash)
    _api_key_repo.deactivate_by_id(key_id)


def list_user_keys(key_id: int) -> list[dict[str, Any]]:
    """Lista las API keys del usuario (solo la key autenticada por ID)."""
    return _api_key_repo.get_by_key_id(key_id)


def get_key_name_and_scopes(key_id: int) -> tuple[str, str] | None:
    """Obtiene nombre y scopes de una API key por ID."""
    return _api_key_repo.get_name_and_scopes(key_id)


def set_key_expiry(key_id: int, expires_at: str) -> None:
    """Establece ``expires_at`` en una API key (para rotación con grace period)."""
    _api_key_repo.set_expiry(key_id, expires_at)
