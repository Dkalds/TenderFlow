"""Service layer for audit trail operations (ADR-013 / §3.8).

Thin wrapper over ``db.audit`` so that dashboard modules never import
``db.*`` directly. Add business logic here if needed in the future.
"""

from __future__ import annotations

from typing import Any

from db.audit import list_recent as _list_recent
from db.audit import log_action as _log_action


def log_action(
    user_key: str,
    session_hash: str,
    action: str,
    detail: str = "",
) -> None:
    """Record a user action in the audit log."""
    _log_action(user_key, session_hash, action, detail)


def list_recent(
    limit: int = 200,
    *,
    user_key: str | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent audit log entries."""
    return _list_recent(limit, user_key=user_key, action=action)
