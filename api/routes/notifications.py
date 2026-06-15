"""Rutas /api/v1/notifications — centro de notificaciones in-app.

Agrega las novedades del usuario (licitaciones publicadas desde su última
visita) con los contadores "para hoy", y rastrea el estado de leídas/no-leídas
vía ``services.notifications``. Pensado para el ``NotificationBell`` del frontend.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from observability.logging import get_logger
from services.analytics.resumen import (
    ResumenHoyFilters,
    get_resumen_hoy,
    get_resumen_novedades,
)
from services.notifications import get_unread_ids, mark_all_read

log = get_logger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave estable por usuario para el seguimiento de lecturas."""
    return str(ctx.get("user_id") or ctx.get("email") or "anon")


class NotificationItem(BaseModel):
    id: str
    titulo: str | None = None
    importe: float | None = None
    organo_contratacion: str | None = None
    read: bool = False


class HoyCounters(BaseModel):
    calientes: int = 0
    vencen_48h: int = 0
    nuevas_24h: int = 0
    total_activas: int = 0


class NotificationsResult(BaseModel):
    items: list[NotificationItem] = Field(default_factory=list)
    unread_count: int = 0
    hoy: HoyCounters = Field(default_factory=HoyCounters)


class MarkReadRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


@router.get("", summary="Notificaciones del usuario (novedades + contadores de hoy)")
async def get_notifications(
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> NotificationsResult:
    user_id = ctx.get("user_id")
    user_key = _user_key(ctx)

    novedades = await run_db(get_resumen_novedades, int(user_id)) if user_id is not None else None
    hoy = await run_db(get_resumen_hoy, ResumenHoyFilters())

    samples = novedades.sample if novedades else []
    candidate_ids = [s.id_externo for s in samples]
    unread_ids = set(await run_db(get_unread_ids, user_key, candidate_ids))

    items = [
        NotificationItem(
            id=s.id_externo,
            titulo=s.titulo,
            importe=s.importe,
            organo_contratacion=s.organo_contratacion,
            read=s.id_externo not in unread_ids,
        )
        for s in samples
    ]
    return NotificationsResult(
        items=items,
        unread_count=len(unread_ids),
        hoy=HoyCounters(**hoy.model_dump()),
    )


@router.post("/read", summary="Marcar notificaciones como leídas")
async def post_mark_read(
    body: MarkReadRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str]:
    if body.ids:
        await run_db(mark_all_read, _user_key(ctx), body.ids)
    return {"status": "ok"}
