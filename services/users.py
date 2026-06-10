"""Service layer for user management (ADR-013 / §3.8).

Thin wrapper over ``db.users`` and ``db.rate_limits`` so that dashboard
modules never import ``db.*`` directly.
"""

from __future__ import annotations

from typing import Any

from db.rate_limits import clear_login_attempts as _clear_login_attempts
from db.rate_limits import is_login_locked_out as _is_login_locked_out
from db.rate_limits import record_failed_login as _record_failed_login
from db.users import deactivate_user as _deactivate_user
from db.users import get_or_create_oauth_user as _get_or_create_oauth_user
from db.users import is_admin as _is_admin
from db.users import list_users as _list_users
from db.users import log_access as _log_access
from db.users import set_admin as _set_admin


# ── User CRUD ──────────────────────────────────────────────────────────────


def get_or_create_oauth_user(
    *,
    email: str,
    oauth_provider: str,
    oauth_sub: str,
    display_name: str | None = None,
) -> int:
    return _get_or_create_oauth_user(
        email=email, oauth_provider=oauth_provider,
        oauth_sub=oauth_sub, display_name=display_name,
    )


def is_admin(user_id: int) -> bool:
    return _is_admin(user_id)


def set_admin(user_id: int, is_admin_value: bool) -> None:
    _set_admin(user_id, is_admin_value)


def list_users(limit: int = 200) -> list[dict[str, Any]]:
    return _list_users(limit)


def deactivate_user(user_id: int) -> None:
    _deactivate_user(user_id)


def log_access(
    *,
    auth_method: str,
    user_id: int | None = None,
    email: str | None = None,
) -> None:
    _log_access(auth_method=auth_method, user_id=user_id, email=email)


# ── Rate limiting ─────────────────────────────────────────────────────────


def is_login_locked_out(client_key: str, max_attempts: int = 5) -> tuple[bool, float]:
    return _is_login_locked_out(client_key, max_attempts)


def record_failed_login(client_key: str) -> int:
    return _record_failed_login(client_key)


def clear_login_attempts(client_key: str) -> None:
    _clear_login_attempts(client_key)
