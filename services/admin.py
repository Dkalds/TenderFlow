"""Servicio de administración — usuarios y API keys.

Centraliza las queries de la página admin para que el dashboard
no haga SQL directo contra ``db.database.connect()``.
"""

from __future__ import annotations

from typing import Any

from db import users as users_db
from db.repositories.api_keys import ApiKeyRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = ApiKeyRepository()


def list_users(limit: int = 200) -> list[dict[str, Any]]:
    """Lista usuarios registrados (con último acceso via access_log)."""
    return users_db.list_users(limit)


def set_admin_by_email(email: str, *, is_admin: bool) -> None:
    """Promueve o degrada un usuario por email."""
    users_db.set_admin_by_email(email, is_admin=is_admin)


def list_api_keys() -> list[dict[str, Any]]:
    """Lista todas las API keys (sin exponer el hash)."""
    return _repo.list_all()


def revoke_api_key(key_id: int) -> None:
    """Revoca una API key por su ID interno."""
    _repo.revoke_by_id(key_id)
