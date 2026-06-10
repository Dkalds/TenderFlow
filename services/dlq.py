"""Service layer for DLQ operations (ADR-013 / §3.8).

Thin wrapper over ``db.dlq`` so that dashboard modules never import
``db.*`` directly.
"""

from __future__ import annotations

from typing import Any

from db.dlq import list_unresolved as _list_unresolved
from db.dlq import mark_matching_resolved as _mark_matching_resolved
from db.dlq import mark_resolved as _mark_resolved
from db.dlq import unresolved_summary as _unresolved_summary


def list_unresolved(limit: int = 100) -> list[dict[str, Any]]:
    return _list_unresolved(limit)


def unresolved_summary() -> list[dict[str, Any]]:
    return _unresolved_summary()


def mark_resolved(failure_id: int) -> None:
    _mark_resolved(failure_id)


def mark_matching_resolved(fuente: str, scope: str | None = None) -> int:
    return _mark_matching_resolved(fuente, scope)
