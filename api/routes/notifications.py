"""Rutas /api/v1/notifications -- centro de notificaciones in-app.

Dos tipos de items:
- ``items``: novedades de licitaciones (existente, basado en last_login del usuario).
- ``alerts``: alertas de reglas de watchlist + recordatorios de deadline (Feature A).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from db.connection import lecturas_agrupadas
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
from shared.dto import DESCRIPCION_GRANDES_EN_PLAZO, StatusOk

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
    #: Oportunidad de la organización sobre ese expediente, si existe: la
    #: campana enlaza a ``/oportunidades/{pursuit_id}`` en vez de al inspector.
    pursuit_id: int | None = None
    read: bool = False


class HoyCounters(BaseModel):
    calientes: int = Field(default=0, description=DESCRIPCION_GRANDES_EN_PLAZO)
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
    # Nota de implementación (fuera del docstring: FastAPI lo publica en el
    # OpenAPI). Cada pestaña pide esta ruta al abrir y en cada evento SSE. Eran
    # cinco `run_db` en serie, cada uno con su conexión y, con la organización
    # fijada, su `BEGIN; SET LOCAL` + consulta + `ROLLBACK`: más de quince
    # viajes y cinco saltos al threadpool. Ahora es un salto, y dentro
    # `lecturas_agrupadas` hace que todas las lecturas compartan una conexión y
    # un ámbito: un `BEGIN; SET LOCAL`, una consulta por lectura y un
    # `ROLLBACK`. El SQL sigue en `db/` (ADR-022): aquí solo se agrupa.
    user_id = _user_id_int(ctx)
    user_key = _user_key(ctx)
    resolved_id = ctx["organization_id"]

    def _trabajo() -> NotificationsResult:
        with lecturas_agrupadas():
            novedades = get_resumen_novedades(int(user_id)) if user_id is not None else None
            hoy = get_resumen_hoy(ResumenHoyFilters())
            samples = novedades.sample if novedades else []
            candidate_ids = [s.id_externo for s in samples]
            unread_ids = set(get_unread_ids(user_key, candidate_ids, user_id=user_id))
            # Alertas in-app (reglas + deadlines) -- Feature A
            raw_alerts = get_user_alerts(user_key, 30, resolved_id, user_id=user_id)
            alerts_unread = get_alerts_unread_count(user_key, resolved_id, user_id=user_id)

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
        alerts = [
            AlertItem(
                id=int(a["id"]),
                created_at=a.get("created_at"),
                type=str(a.get("type", "")),
                title=a.get("title"),
                body=a.get("body"),
                licitacion_id=a.get("licitacion_id"),
                rule_id=a.get("rule_id"),
                pursuit_id=a.get("pursuit_id"),
                read=a.get("read_at") is not None,
            )
            for a in raw_alerts
        ]
        return NotificationsResult(
            items=items,
            unread_count=len(unread_ids),
            alerts=alerts,
            alerts_unread_count=alerts_unread,
            hoy=HoyCounters(**hoy.model_dump()),
        )

    return await run_db(_trabajo)


@router.post("/read", summary="Marcar novedades como leidas")
async def post_mark_read(
    body: MarkReadRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    if body.ids:
        await run_db(mark_all_read, _user_key(ctx), body.ids, user_id=_user_id_int(ctx))
    return StatusOk(status="ok")


@router.post("/alerts/read", summary="Marcar alertas como leidas")
async def post_mark_alerts_read(
    body: MarkAlertsReadRequest,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    ctx = await resolve_organization_ctx(ctx, body.organization_id, write=True)
    user_key = _user_key(ctx)
    user_id = _user_id_int(ctx)
    resolved_id = ctx["organization_id"]
    if body.all:
        await run_db(mark_all_alerts_read, user_key, resolved_id, user_id=user_id)
    elif body.ids:
        await run_db(mark_alerts_read, user_key, body.ids, resolved_id, user_id=user_id)
    return StatusOk(status="ok")


# ── Baja de un tipo de notificación desde el correo ─────────────────────────


def _apagar_por_enlace(user_id: int, tipo: str, token: str) -> tuple[bool, str | None]:
    """Verifica la firma y apaga el canal ``email`` de ese tipo.

    Devuelve ``(firma_valida, destino)`` en vez de lanzar: la ``HTTPException``
    es del handler y no del trabajo despachado al threadpool. Firma y escritura
    van en el mismo salto porque la primera es HMAC (CPU) y la segunda una
    escritura, y las dos en el event loop lo bloquearían.
    """
    from db.repositories.notification_preferences import TIPOS, apagar_canal
    from services.app_urls import url_absoluta
    from services.email_digest import verificar_token_de_baja_de_tipo

    if tipo not in {t for t, _ in TIPOS}:
        return False, None
    if not verificar_token_de_baja_de_tipo(user_id, tipo, token):
        return False, None
    # Sólo el canal `email`: quien se da de baja del correo no está pidiendo
    # dejar de verlo en la aplicación. Y `apagar_canal` y no `guardar`, porque
    # la preferencia de una organización concreta gana sobre la global: apagar
    # sólo la global dejaba el enlace sin efecto para quien tuviera una.
    apagar_canal(user_id, tipo=tipo, canal="email")
    return True, url_absoluta("/ajustes?baja=1")


@router.get(
    "/baja",
    response_model=StatusOk,
    summary="Dejar de recibir por correo un tipo de notificación",
    responses={
        303: {"description": "Redirige a Ajustes con el tipo ya apagado"},
        403: {"description": "Firma inválida o tipo desconocido"},
    },
)
async def baja_de_tipo(
    u: int = Query(..., ge=1, description="Usuario"),
    tipo: str = Query(..., min_length=3, max_length=60, description="Tipo de notificación"),
    t: str = Query(..., min_length=8, max_length=200, description="Firma HMAC (kid.sig)"),
) -> Any:
    """Apaga el correo de **un** tipo, y nada más.

    Sin sesión a propósito: quien quiere dejar de recibir un correo no quiere
    antes hacer login. Lo que autoriza es la firma de ``(user_id, tipo)``.

    Existe porque la baja del digest (``/watchlist/rules/baja``) pausa **todas
    las reglas de watchlist**, y el informe semanal salió apuntando ahí: pulsar
    «dejar de recibir este informe» borraba las alertas de licitaciones de esa
    persona y el informe seguía llegando, porque su opt-out está en
    ``notification_preferences``. Un enlace de baja que da de baja de otra cosa
    es peor que no tener enlace.
    """
    valida, destino = await run_db(_apagar_por_enlace, u, tipo, t)
    if not valida:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Enlace no válido.")
    log.info("notificacion_baja", user_id=u, tipo=tipo)
    if destino:
        return RedirectResponse(destino, status_code=status.HTTP_303_SEE_OTHER)
    return StatusOk(status="ok")


@router.post(
    "/baja",
    response_model=StatusOk,
    summary="Baja en un clic desde el cliente de correo (RFC 8058)",
    responses={403: {"description": "Firma inválida o tipo desconocido"}},
)
async def baja_de_tipo_un_clic(
    u: int = Query(..., ge=1, description="Usuario"),
    tipo: str = Query(..., min_length=3, max_length=60, description="Tipo de notificación"),
    t: str = Query(..., min_length=8, max_length=200, description="Firma HMAC (kid.sig)"),
) -> StatusOk:
    """La misma baja que el GET, para el ``POST`` del cliente de correo.

    RFC 8058 exige responder 2xx y **no** redirigir: el cliente no sigue la
    redirección y daría la baja por fallida.
    """
    valida, _destino = await run_db(_apagar_por_enlace, u, tipo, t)
    if not valida:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Enlace no válido.")
    log.info("notificacion_baja_un_clic", user_id=u, tipo=tipo)
    return StatusOk(status="ok")
