"""La sesión abierta: ``GET /auth/me`` y ``POST /auth/logout``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from api.concurrency import run_db
from api.routes.auth.comun import (
    UserInfo,
    _clear_session_cookies,
    get_session_user_pending_mfa,
    require_csrf_pending_mfa,
)
from db.audit import log_event
from db.sessions import revoke_session
from shared.audit_events import AUTH_LOGOUT
from shared.dto import DetailMessage
from shared.identity import Principal

router = APIRouter()


@router.get("/me", response_model=UserInfo)
async def me(user: Principal = Depends(get_session_user_pending_mfa)) -> UserInfo:
    """Return info about the currently authenticated user.

    Accesible con MFA pendiente: es la respuesta que le dice al SPA que debe
    pedir el TOTP. Solo devuelve identidad, nunca datos de negocio.
    """
    return UserInfo(
        user_id=user["user_id"],
        email=user.get("email"),
        display_name=user.get("display_name"),
        is_admin=user.get("is_admin", False),
        mfa_required=bool(user.get("mfa_required")),
    )


@router.post("/logout")
async def logout(
    response: Response,
    user: Principal = Depends(require_csrf_pending_mfa),
) -> DetailMessage:
    """Revoca la sesión server-side y borra sus cookies.

    Debe funcionar con MFA pendiente: abandonar un login a medias no puede
    requerir completarlo.
    """
    await run_db(revoke_session, str(user["session_token"]))
    await run_db(
        log_event,
        event_type=AUTH_LOGOUT,
        user_id=int(user["user_id"]),
        resource=f"user:{user['user_id']}",
    )
    _clear_session_cookies(response)
    return DetailMessage(detail="Logged out")
