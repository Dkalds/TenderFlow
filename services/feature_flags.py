"""Service layer for feature flags (ADR-013 / §3.8).

Thin wrapper over ``db.feature_flags`` so that dashboard modules never
import ``db.*`` directly.
"""

from __future__ import annotations

from typing import Any

from db.feature_flags import delete_flag as _delete_flag
from db.feature_flags import list_flags as _list_flags
from db.feature_flags import set_flag as _set_flag


def list_flags() -> list[dict[str, Any]]:
    return _list_flags()


def set_flag(
    name: str,
    *,
    enabled: bool = True,
    rollout_pct: int = 100,
    user_emails: str = "",
    description: str = "",
) -> None:
    _set_flag(name, enabled=enabled, rollout_pct=rollout_pct, user_emails=user_emails, description=description)


def delete_flag(name: str) -> bool:
    return _delete_flag(name)
