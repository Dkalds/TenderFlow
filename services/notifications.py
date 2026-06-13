"""Service layer for notifications (ADR-013 / §3.8).

Thin wrapper over ``db.notifications`` so that dashboard modules never
import ``db.*`` directly.
"""

from __future__ import annotations

from db.notifications import get_unread_ids as _get_unread_ids
from db.notifications import mark_all_read as _mark_all_read
from db.notifications import mark_read as _mark_read


def mark_read(user_key: str, notification_id: str) -> None:
    """Mark a single notification as read."""
    _mark_read(user_key, notification_id)


def mark_all_read(user_key: str, notification_ids: list[str]) -> None:
    """Mark a batch of notifications as read."""
    _mark_all_read(user_key, notification_ids)


def get_unread_ids(user_key: str, candidate_ids: list[str]) -> list[str]:
    """Return IDs from candidate_ids that the user has NOT read."""
    return _get_unread_ids(user_key, candidate_ids)
