"""Rutas /api/v1/notifications -- la campana: lo que concierne a cada persona.

La campana enseña **solo lo tuyo** (decisión de producto del 2026-10-12): lo
que el canal ``in_app`` del outbox y los productores directos dejan en
``user_notifications`` —alertas de tus reglas, cambios en lo que sigues,
menciones, tareas y plazos de tus oportunidades, caducidades de la
documentación de tu organización—. Las novedades del mercado no son de nadie en
concreto y las cubre el Resumen.

- ``GET /notifications/alerts``: la bandeja, paginada y con filtro de lectura.
  Es lo que pide la campana, tanto su vista previa como «Ver todas».
- ``POST /notifications/alerts/read``: leída una a una al abrirla, o todas con
  la acción explícita «Marcar todo como leído».
- ``GET /notifications``: el resumen de antes, conservado por compatibilidad.
  Sus campos de mercado (``items``, ``unread_count``, ``hoy``) están
  deprecados: retirarlos es un cambio incompatible del contrato y va por RFC
  (``docs/api-design.md``).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from api.tenancy import require_organization, resolve_organization_ctx
from db.connection import lecturas_agrupadas
from db.notifications import listar_alertas
from observability.logging import get_logger
from services.analytics.resumen import ResumenHoyFilters, get_resumen_hoy
from services.notifications import (
    get_alerts_unread_count,
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


#: Marca de deprecación en el esquema y **solo** en el esquema. No es
#: ``Field(deprecated=True)`` a propósito: Pydantic emite entonces un
#: ``DeprecationWarning`` cada vez que el servidor lee el atributo para
#: serializarlo, y lo que se quiere avisar es al consumidor del contrato.
_DEPRECADO: dict[str, Any] = {"deprecated": True}


class NotificationsResult(BaseModel):
    items: list[NotificationItem] = Field(
        default_factory=list,
        description=(
            "Deprecado: siempre vacío. La campana ya no lista novedades del mercado; "
            "están en GET /analytics/resumen/novedades."
        ),
        json_schema_extra=_DEPRECADO,
    )
    unread_count: int = Field(
        default=0,
        description="Deprecado: siempre 0 (acompañaba a `items`).",
        json_schema_extra=_DEPRECADO,
    )
    alerts: list[AlertItem] = Field(default_factory=list)
    alerts_unread_count: int = 0
    hoy: HoyCounters = Field(
        default_factory=HoyCounters,
        description=(
            "Deprecado: contadores del mercado, que la campana ya no pinta. "
            "Los mismos, con el ámbito de la barra, en GET /analytics/resumen/hoy."
        ),
        json_schema_extra=_DEPRECADO,
    )


#: Filtro de lectura de la bandeja. Espejo de ``db.notifications.EstadoLectura``.
EstadoLectura = Literal["todas", "sin_leer", "leidas"]


class AlertasPagina(BaseModel):
    """Una página de la bandeja de la campana."""

    items: list[AlertItem]
    total: int = Field(ge=0, description="Alertas que cumplen el filtro, en todas las páginas.")
    sin_leer: int = Field(
        ge=0,
        description="Alertas sin leer, sea cual sea el filtro: el número del distintivo.",
    )
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


def _alerta(fila: dict[str, Any]) -> AlertItem:
    """Fila de ``user_notifications`` (con ``pursuit_id`` resuelto) a contrato."""
    return AlertItem(
        id=int(fila["id"]),
        created_at=fila.get("created_at"),
        type=str(fila.get("type", "")),
        title=fila.get("title"),
        body=fila.get("body"),
        licitacion_id=fila.get("licitacion_id"),
        rule_id=fila.get("rule_id"),
        pursuit_id=fila.get("pursuit_id"),
        read=fila.get("read_at") is not None,
    )


class MarkReadRequest(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=200)


class MarkAlertsReadRequest(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=200)
    all: bool = False
    organization_id: int | None = Field(default=None, ge=1)


@router.get("", summary="Resumen de notificaciones (alertas; campos de mercado deprecados)")
async def get_notifications(
    ctx: dict[str, Any] = Depends(require_organization()),
) -> NotificationsResult:
    # Nota de implementación (fuera del docstring: FastAPI lo publica en el
    # OpenAPI). Las lecturas comparten una conexión y un ámbito
    # (`lecturas_agrupadas`): un `BEGIN; SET LOCAL`, una consulta por lectura y
    # un `ROLLBACK`, en un solo salto al threadpool. El SQL sigue en `db/`.
    #
    # `items` ya no se calcula: salía de `get_resumen_novedades(user_id)`, que
    # contaba desde `users.last_login`, una columna que ninguna migración crea,
    # así que siempre llegaba vacío. Se retiró con la decisión de que la campana
    # enseñe solo lo tuyo; el campo sigue en el contrato, vacío y deprecado,
    # porque quitarlo rompería a quien lo lea. `hoy` se sigue sirviendo por lo
    # mismo, aunque la campana ya no lo pinte.
    user_id = _user_id_int(ctx)
    user_key = _user_key(ctx)
    resolved_id = ctx["organization_id"]

    def _trabajo() -> NotificationsResult:
        with lecturas_agrupadas():
            hoy = get_resumen_hoy(ResumenHoyFilters())
            raw_alerts = get_user_alerts(user_key, 30, resolved_id, user_id=user_id)
            alerts_unread = get_alerts_unread_count(user_key, resolved_id, user_id=user_id)

        return NotificationsResult(
            alerts=[_alerta(a) for a in raw_alerts],
            alerts_unread_count=alerts_unread,
            hoy=HoyCounters(**hoy.model_dump()),
        )

    return await run_db(_trabajo)


@router.get(
    "/alerts",
    response_model=AlertasPagina,
    summary="Bandeja de la campana: tus alertas, paginadas y con filtro de lectura",
)
async def get_alertas(
    estado: EstadoLectura = Query(default="todas", description="`todas`, `sin_leer` o `leidas`."),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    ctx: dict[str, Any] = Depends(require_organization()),
) -> AlertasPagina:
    """Lo que te concierne en la organización activa, lo más reciente arriba.

    Alertas de tus reglas, cambios en lo que sigues, menciones, tareas y plazos
    de tus oportunidades y avisos de tu organización. **Leer no marca nada**:
    cada alerta se marca al abrirla, o todas con ``POST /notifications/alerts/read``
    y ``all=true``. ``sin_leer`` no depende del filtro.
    """
    pagina = await run_db(
        listar_alertas,
        _user_key(ctx),
        int(ctx["organization_id"]),
        user_id=_user_id_int(ctx),
        estado=estado,
        limit=limit,
        offset=offset,
    )
    return AlertasPagina(
        items=[_alerta(fila) for fila in pagina["items"]],
        total=pagina["total"],
        sin_leer=pagina["sin_leer"],
        limit=limit,
        offset=offset,
    )


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
