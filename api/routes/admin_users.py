"""Admin endpoints — gestión de usuarios (RFC UX Administración).

Requiere autenticación dual (session o API key) + is_admin.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.routes.dual_auth import require_admin
from db.audit import log_event
from db.sessions import revoke_all_sessions
from db.users import (
    anonymize_user,
    deactivate_user,
    get_user_by_id,
    list_users,
    reactivate_user,
    set_admin,
)
from observability.logging import get_logger
from services.gdpr import revoke_all_api_keys_for_user

log = get_logger(__name__)

router = APIRouter(prefix="/admin/users", tags=["admin"])


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
    # Sin cota, un `limit` negativo llegaba tal cual al `LIMIT` de la query y
    # Postgres respondía con InvalidRowCountInLimitClause -> 500. Acotarlo aquí
    # lo convierte en el 422 que corresponde a un parámetro inválido.
    limit: int = Query(200, ge=1, le=1000),
    admin: dict[str, Any] = Depends(require_admin),
) -> list[AdminUserOut]:
    """Lista todos los usuarios (solo admin)."""
    return [
        _safe_user(user)
        for user in list_users(limit=limit, include_deactivated=include_deactivated)
    ]


@router.get("/{user_id}")
def admin_get_user(
    user_id: int,
    admin: dict[str, Any] = Depends(require_admin),
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
    admin: dict[str, Any] = Depends(require_admin),
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
    admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, str]:
    """Desactivar, reactivar o anonimizar un usuario.

    Dar de baja o anonimizar revoca además sesiones y API keys ya emitidas: el
    soft-delete de ``users`` solo impide autenticaciones nuevas, así que sin
    esto una baja dejaba vivas todas las credenciales que el usuario ya tenía
    en la mano. Es la misma limpieza que hace el borrado GDPR self-service
    (``api.routes.me.delete_my_data``). ``reactivate`` no revoca nada porque no
    hay credencial que invalidar.
    """
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

    detail: dict[str, Any] = {"action": body.action}
    if body.action in ("deactivate", "anonymize"):
        detail["sessions_revoked"] = revoke_all_sessions(user_id)
        detail["api_keys_revoked"] = revoke_all_api_keys_for_user(user_id)
        log.info(
            "admin_user_credentials_revoked",
            user_id=user_id,
            action=body.action,
            sessions_revoked=detail["sessions_revoked"],
            api_keys_revoked=detail["api_keys_revoked"],
        )

    log_event(
        event_type=f"user.{body.action}",
        user_key=str(admin.get("user_id", "")),
        resource=f"user:{user_id}",
        detail=detail,
    )
    return {"status": "ok", "action": body.action}
