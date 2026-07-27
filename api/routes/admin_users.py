"""Admin endpoints — gestión de usuarios (RFC UX Administración).

Requiere autenticación dual (session o API key) + is_admin.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.routes.dual_auth import require_any_auth
from db.audit import log_event
from db.users import (
    anonymize_user,
    deactivate_user,
    get_user_by_id,
    list_users,
    reactivate_user,
    set_admin,
)
from observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _require_admin(user: dict[str, Any] = Depends(require_any_auth)) -> dict[str, Any]:
    """Verifica que el usuario autenticado sea admin."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    return user


class SetAdminBody(BaseModel):
    is_admin: bool


class DeactivateBody(BaseModel):
    action: str  # "deactivate" | "reactivate" | "anonymize"


class AdminUserOut(BaseModel):
    """Vista segura de usuario para administración; excluye credenciales."""

    id: int
    email: str | None = None
    display_name: str | None = None
    oauth_provider: str | None = None
    is_admin: bool = False
    created_at: str | None = None
    deactivated_at: str | None = None
    last_access: str | None = None


def _safe_user(user: dict[str, Any]) -> AdminUserOut:
    return AdminUserOut(
        id=int(user["id"]),
        email=user.get("email"),
        display_name=user.get("display_name"),
        oauth_provider=user.get("oauth_provider"),
        is_admin=bool(user.get("is_admin")),
        created_at=user.get("created_at"),
        deactivated_at=user.get("deactivated_at"),
        last_access=user.get("last_access"),
    )


@router.get("")
def admin_list_users(
    include_deactivated: bool = False,
    limit: int = 200,
    admin: dict[str, Any] = Depends(_require_admin),
) -> list[AdminUserOut]:
    """Lista todos los usuarios (solo admin)."""
    return [
        _safe_user(user)
        for user in list_users(limit=limit, include_deactivated=include_deactivated)
    ]


@router.get("/{user_id}")
def admin_get_user(
    user_id: int,
    admin: dict[str, Any] = Depends(_require_admin),
) -> AdminUserOut:
    """Detalle de un usuario (incluye desactivados)."""
    user = get_user_by_id(user_id, include_deactivated=True)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _safe_user(user)


@router.put("/{user_id}/admin")
def admin_set_admin(
    user_id: int,
    body: SetAdminBody,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, str]:
    """Promover/degradar admin de un usuario."""
    if user_id == admin.get("user_id"):
        raise HTTPException(status_code=400, detail="Cannot change own admin status.")
    target = get_user_by_id(user_id, include_deactivated=True)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")
    set_admin(user_id, body.is_admin)
    log_event(
        event_type="user.admin_changed",
        user_key=str(admin.get("user_id", "")),
        resource=f"user:{user_id}",
        detail=f"is_admin={body.is_admin}",
    )
    return {"status": "ok"}


@router.post("/{user_id}/deactivate")
def admin_deactivate_user(
    user_id: int,
    body: DeactivateBody,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, str]:
    """Desactivar, reactivar o anonimizar un usuario."""
    if user_id == admin.get("user_id"):
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself.")
    target = get_user_by_id(user_id, include_deactivated=True)
    if target is None:
        raise HTTPException(status_code=404, detail="User not found.")

    if body.action == "deactivate":
        deactivate_user(user_id)
    elif body.action == "reactivate":
        reactivate_user(user_id)
    elif body.action == "anonymize":
        anonymize_user(user_id)
    else:
        raise HTTPException(
            status_code=400, detail="Invalid action. Use: deactivate|reactivate|anonymize."
        )

    log_event(
        event_type=f"user.{body.action}",
        user_key=str(admin.get("user_id", "")),
        resource=f"user:{user_id}",
        detail=body.action,
    )
    return {"status": "ok", "action": body.action}
