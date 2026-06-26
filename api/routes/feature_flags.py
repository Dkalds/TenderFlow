"""Feature flags endpoints (RFC UX Feature Flags).

La lista de flags la dirige el **backend** (`services.feature_flags`), no una
constante hardcodeada en el frontend. GET para cualquier usuario autenticado;
PUT (toggle/rollout) solo admin, con auditoría.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from api.routes.dual_auth import require_any_auth
from db.audit import log_event
from observability.logging import get_logger
from services.feature_flags import list_flags, set_flag

log = get_logger(__name__)

router = APIRouter(prefix="/feature-flags", tags=["feature-flags"])


class FlagOut(BaseModel):
    """Flag tal y como lo expone el backend (fuente de verdad)."""

    flag: str
    enabled: bool
    rollout_pct: int
    description: str = ""
    updated_at: str | None = None


class FlagIn(BaseModel):
    flag: str
    enabled: bool
    rollout_pct: int = 100


class SetFlagsBody(BaseModel):
    flags: list[FlagIn]


def _require_admin(user: dict[str, Any] = Depends(require_any_auth)) -> dict[str, Any]:
    if not user.get("is_admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    return user


@router.get("", response_model=list[FlagOut])
def get_feature_flags(
    _user: dict[str, Any] = Depends(require_any_auth),
) -> list[FlagOut]:
    """Lista TODOS los flags del backend (incl. los que no estaban en ningún hardcode)."""
    return [
        FlagOut(
            flag=str(f["name"]),
            enabled=bool(f.get("enabled")),
            rollout_pct=int(f.get("rollout_pct") or 0),
            description=str(f.get("description") or ""),
            updated_at=f.get("updated_at"),
        )
        for f in list_flags()
    ]


@router.put("")
def set_feature_flags(
    body: SetFlagsBody,
    admin: dict[str, Any] = Depends(_require_admin),
) -> dict[str, str]:
    """Persiste enabled/rollout de los flags (solo admin), auditando cada cambio.

    Preserva ``description``/``user_emails`` existentes (el toggle no debe borrarlos).
    """
    current = {f["name"]: f for f in list_flags()}
    for f in body.flags:
        existing = current.get(f.flag, {})
        set_flag(
            f.flag,
            enabled=f.enabled,
            rollout_pct=f.rollout_pct,
            user_emails=str(existing.get("user_emails") or ""),
            description=str(existing.get("description") or ""),
        )
        log_event(
            event_type="feature_flag.set",
            user_key=str(admin.get("user_id", "")),
            resource=f"feature_flag:{f.flag}",
            detail=f"enabled={f.enabled} rollout_pct={f.rollout_pct}",
        )
    return {"status": "ok"}
