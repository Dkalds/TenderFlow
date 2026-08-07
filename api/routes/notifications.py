"""Rutas /api/v1/notifications -- centro de notificaciones in-app.

Dos tipos de items:
- ``items``: novedades de licitaciones (existente, basado en last_login del usuario).
- ``alerts``: alertas de reglas de watchlist + recordatorios de deadline (Feature A).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from observability.logging import get_logger
from services.analytics.resumen import ResumenHoyFilters, get_resumen_hoy, get_resumen_novedades
from services.notifications import (
    get_alerts_unread_count,
    get_unread_ids,
    get_user_alerts,
    mark_alerts_read,
    mark_all_alerts_read,
    mark_all_read,
)
from shared.dto import StatusOk

log = get_logger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


def _user_key(ctx: dict[str, Any]) -> str:
    """Clave opaca y estable por usuario.

    ``require_any_auth`` (sesión o API key) siempre adjunta ``user_key`` al
    contexto vía ``shared.identity.user_key_from_email`` — es la única
    derivación canónica. Antes esta función tenía un fallback local con una
    fórmula distinta (sin ``.strip().lower()``, usando ``key_hash`` en vez de
    ``user_id`` como semilla alternativa) que nunca se ejercitaba en la
    práctica pero podía divergir silenciosamente si algún día lo hiciera.
    """
    return str(ctx["user_key"])


def _user_id_int(ctx: dict[str, Any]) -> int | None:
    uid = ctx.get("user_id")
    try:
        return int(uid) if uid is not None else None
    except (ValueError, TypeError):
        return None


class NotificationItem(BaseModel):
    id: str
    titulo: str | None = None
    importe: float | None = None
    organo_contratacion: str | None = None
    read: bool = False


class AlertItem(BaseModel):
    id: int
    created_at: str | None = None
    type: str
    title: str | None = None
    body: str | None = None
    licitacion_id: str | None = None
    rule_id: int | None = None
    read: bool = False


class HoyCounters(BaseModel):
    calientes: int = 0
    vencen_48h: int = 0
    nuevas_24h: int = 0
    total_activas: int = 0


class NotificationsResult(BaseModel):
    items: list[NotificationItem] = Field(default_factory=list)
    unread_count: int = 0
    alerts: list[AlertItem] = Field(default_factory=list)
    alerts_unread_count: int = 0
    hoy: HoyCounters = Field(default_factory=HoyCounters)


class MarkReadRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


class MarkAlertsReadRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=200)
    all: bool = False
    organization_id: int | None = Field(default=None, ge=1)


@router.get("", summary="Notificaciones del usuario (novedades + alertas + contadores de hoy)")
async def get_notifications(
    ctx: dict[str, Any] = Depends(require_organization()),
) -> NotificationsResult:
    user_id = _user_id_int(ctx)
    user_key = _user_key(ctx)
    resolved_id = ctx["organization_id"]

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

    # Alertas in-app (reglas + deadlines) -- Feature A
    raw_alerts = await run_db(get_user_alerts, user_key, 30, resolved_id)
    alerts = [
        AlertItem(
            id=int(a["id"]),
            created_at=a.get("created_at"),
            type=str(a.get("type", "")),
            title=a.get("title"),
            body=a.get("body"),
            licitacion_id=a.get("licitacion_id"),
            rule_id=a.get("rule_id"),
            read=a.get("read_at") is not None,
        )
        for a in raw_alerts
    ]
    alerts_unread = await run_db(get_alerts_unread_count, user_key, resolved_id)

    return NotificationsResult(
        items=items,
        unread_count=len(unread_ids),
        alerts=alerts,
        alerts_unread_count=alerts_unread,
        hoy=HoyCounters(**hoy.model_dump()),
    )


@router.post("/read", summary="Marcar novedades como leidas")
async def post_mark_read(
    body: MarkReadRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    if body.ids:
        await run_db(mark_all_read, _user_key(ctx), body.ids)
    return StatusOk(status="ok")


@router.post("/alerts/read", summary="Marcar alertas como leidas")
async def post_mark_alerts_read(
    body: MarkAlertsReadRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    user_key = _user_key(ctx)
    resolved_id = ctx["organization_id"]
    if body.all:
        await run_db(mark_all_alerts_read, user_key, resolved_id)
    elif body.ids:
        await run_db(mark_alerts_read, user_key, body.ids, resolved_id)
    return StatusOk(status="ok")
