"""Servicio de administración — usuarios y API keys.

Centraliza las queries de la página admin para que el dashboard
no haga SQL directo contra ``db.database.connect()``.
"""

from __future__ import annotations

from typing import Any

from db.database import connect, connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


def list_users(limit: int = 200) -> list[dict[str, Any]]:
    """Lista usuarios registrados (sin JOIN a access_log)."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT id, email, oauth_provider, display_name, created_at, is_admin "
            "FROM users ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return rows_to_dicts(cur)


def set_admin_by_email(email: str, *, is_admin: bool) -> None:
    """Promueve o degrada un usuario por email."""
    with connect() as c:
        c.execute(
            "UPDATE users SET is_admin = ? WHERE email = ?",
            (1 if is_admin else 0, email),
        )


def list_api_keys() -> list[dict[str, Any]]:
    """Lista todas las API keys (sin exponer el hash)."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT id, name, created_at, last_used, is_active "
            "FROM api_keys ORDER BY created_at DESC"
        )
        return rows_to_dicts(cur)


def revoke_api_key(key_id: int) -> None:
    """Revoca una API key por su ID interno."""
    with connect() as c:
        c.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?", (key_id,))
