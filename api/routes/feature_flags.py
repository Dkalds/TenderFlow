"""Feature flags endpoints (RFC UX Feature Flags).

La lista de flags la dirige el **backend** (`db.feature_flags`), no una
constante hardcodeada en el frontend. GET para cualquier usuario autenticado;
PUT (toggle/rollout) solo admin, con auditoría.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.routes.dual_auth import require_admin, require_any_auth
from db.audit import log_event
from db.feature_flags import FLAGS_DECLARADAS, list_flags, set_flag
from observability.logging import get_logger
from shared.audit_events import FEATURE_FLAG_SET
from shared.dto import SafeStr, StatusOk

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
    # Ver BulkGetRequest: el NUL se rechaza en el contrato, no por endpoint.
    flag: SafeStr
    enabled: bool
    rollout_pct: int = 100


class SetFlagsBody(BaseModel):
    flags: list[FlagIn]


@router.get("", response_model=list[FlagOut])
def get_feature_flags(
    _user: dict[str, Any] = Depends(require_any_auth),
) -> list[FlagOut]:
    """Lista TODOS los flags del backend (incl. los que no estaban en ningún hardcode).

    Las declaradas en ``db.feature_flags.FLAGS_DECLARADAS`` que aún no tienen
    fila salen apagadas y sin ``updated_at``: es su estado real (sin fila,
    ``is_enabled`` dice False), y así Administración puede encenderlas.
    """
    guardadas = [
        FlagOut(
            flag=str(f["name"]),
            enabled=bool(f.get("enabled")),
            rollout_pct=int(f.get("rollout_pct") or 0),
            description=str(f.get("description") or FLAGS_DECLARADAS.get(str(f["name"]), "")),
            updated_at=f.get("updated_at"),
        )
        for f in list_flags()
    ]
    con_fila = {f.flag for f in guardadas}
    sin_fila = [
        FlagOut(flag=nombre, enabled=False, rollout_pct=0, description=descripcion)
        for nombre, descripcion in FLAGS_DECLARADAS.items()
        if nombre not in con_fila
    ]
    return sorted([*guardadas, *sin_fila], key=lambda f: f.flag)


@router.put("")
def set_feature_flags(
    body: SetFlagsBody,
    admin: dict[str, Any] = Depends(require_admin),
) -> StatusOk:
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
            description=str(existing.get("description") or FLAGS_DECLARADAS.get(f.flag, "")),
        )
        log_event(
            event_type=FEATURE_FLAG_SET,
            actor=str(admin.get("user_id", "")),
            resource=f"feature_flag:{f.flag}",
            detail=f"enabled={f.enabled} rollout_pct={f.rollout_pct}",
        )
    return StatusOk(status="ok")
