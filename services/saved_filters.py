"""Service layer for saved filters (ADR-013 / §3.8).

Thin wrapper over ``db.saved_filters`` so that dashboard modules never
import ``db.*`` directly.
"""

from __future__ import annotations

from typing import Any

from db.saved_filters import delete_saved_filter as _delete_saved_filter
from db.saved_filters import filters_to_json as _filters_to_json
from db.saved_filters import json_to_session_state as _json_to_session_state
from db.saved_filters import list_saved_filters as _list_saved_filters
from db.saved_filters import save_filter as _save_filter


# ``organization_id`` viaja hasta aquí en vez de quedarse en la ruta: el
# CRUD de abajo dejó de admitir ``None`` (ver ``db/saved_filters.py``) y
# una fachada que lo omitiera reintroduciría el fail-open que se retira.
def save_filter(user_key: str, name: str, filters_json: str, organization_id: int) -> None:
    _save_filter(user_key, name, filters_json, organization_id)


def list_saved_filters(user_key: str, organization_id: int) -> list[dict[str, Any]]:
    return _list_saved_filters(user_key, organization_id)


def delete_saved_filter(filter_id: int, user_key: str, organization_id: int) -> None:
    _delete_saved_filter(filter_id, user_key=user_key, organization_id=organization_id)


def filters_to_json(
    filters_state: Any, *, nav_section: str | None = None, detalle_cols: list[str] | None = None
) -> str:
    return _filters_to_json(filters_state, nav_section=nav_section, detalle_cols=detalle_cols)


def json_to_session_state(filters_json: str) -> dict[str, Any]:
    return _json_to_session_state(filters_json)
