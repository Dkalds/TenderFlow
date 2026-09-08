"""API colaborativa de organizaciones y oportunidades."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth, require_recent_session
from db.repositories.pursuits import PursuitRepository
from observability.logging import get_logger
from services.cartera import ContratoCartera, cartera_de_usuario
from services.direccion import (
    CuadroDireccion,
    FeedActividad,
    actividad_de_organizacion,
    corte_con_minimo,
    exigir_direccion,
)
from services.gonogo import GoNoGoError
from services.gonogo import guardar_ajustes as guardar_ajustes_gonogo
from services.gonogo import leer_ajustes as leer_ajustes_gonogo
from services.gonogo import puntuar as puntuar_gonogo
from services.kit_presentacion import KitPresentacion
from services.organizations import (
    OrganizationAccessError,
    OrganizationInvitationNotFoundError,
    OrganizationLifecycleError,
    OrganizationMemberNotFoundError,
    OrganizationPermissionError,
    accept_invitation_token,
    borrar_organizacion,
    create_organization,
    get_active_organization,
    invite_member_by_email,
    list_invitations,
    list_members,
    list_organizations,
    resend_invitation,
    resumen_de_borrado,
    revoke_invitation,
    salir_de_organizacion,
    transferir_propiedad,
    upsert_membership,
)
from services.pursuit_attachments import (
    AttachmentError,
    AttachmentNotFoundError,
    AttachmentStoreError,
)
from services.pursuit_attachments import borrar as borrar_adjunto
from services.pursuit_attachments import descargar as descargar_adjunto
from services.pursuit_attachments import firmar_descarga as firmar_descarga_adjunto
from services.pursuit_attachments import listar as listar_adjuntos
from services.pursuit_attachments import marcar_indexable as marcar_adjunto_indexable
from services.pursuit_attachments import subir as subir_adjunto
from services.pursuit_comments import (
    PursuitCommentNotFoundError,
    add_comment,
    delete_comment,
    list_comments,
)
from services.pursuit_tasks import (
    PursuitTaskNotFoundError,
    add_task,
    list_tasks,
    update_task,
)
from services.pursuit_tasks import agenda as tasks_agenda
from services.pursuits import (
    PesosPropuestos,
    PesosPropuestosAplicados,
    PursuitConflictError,
    PursuitNotFoundError,
    PursuitTransitionError,
    PursuitValidationError,
    apply_weights_proposal,
    baja_propia,
    create_pursuit,
    ficha_pdf,
    get_agenda,
    get_metrics,
    get_pursuit,
    get_weights_proposal,
    kit_de_pursuit,
    list_pursuits,
    marcar_kit_de_pursuit,
    update_pursuit,
)
from shared.dto import (
    BajaPropiaResult,
    GoNoGoAjustes,
    GoNoGoPesos,
    GoNoGoPuntuaciones,
    GoNoGoResult,
    OrganizationCreate,
    OrganizationInvitationAccept,
    OrganizationInvitationOut,
    OrganizationMemberInvite,
    OrganizationMembershipOut,
    OrganizationMembershipUpsert,
    OrganizationSummary,
    PipelineAgendaResponse,
    PursuitAttachmentDownloadLink,
    PursuitAttachmentIndexable,
    PursuitAttachmentListResponse,
    PursuitAttachmentOut,
    PursuitCommentCreate,
    PursuitCommentListResponse,
    PursuitCommentOut,
    PursuitCreate,
    PursuitDetail,
    PursuitListResponse,
    PursuitMetrics,
    PursuitStatus,
    PursuitSummary,
    PursuitTaskAgendaResponse,
    PursuitTaskCreate,
    PursuitTaskListResponse,
    PursuitTaskOut,
    PursuitTaskUpdate,
    PursuitUpdate,
    StatusOk,
)

log = get_logger(__name__)
router = APIRouter(tags=["pursuits"])

_pursuit_repo = PursuitRepository()


@router.get("/organizations", response_model=list[OrganizationSummary])
async def get_organizations(
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[OrganizationSummary]:
    """Lista las organizaciones activas del principal."""
    return await run_db(list_organizations, int(ctx["user_id"]))


@router.post(
    "/organizations",
    response_model=OrganizationSummary,
    status_code=status.HTTP_201_CREATED,
)
async def post_organization(
    body: OrganizationCreate,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationSummary:
    return await run_db(create_organization, int(ctx["user_id"]), body.name)


@router.get("/organizations/active", response_model=OrganizationSummary)
async def get_active_organization_route(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationSummary:
    try:
        return await run_db(
            get_active_organization,
            int(ctx["user_id"]),
            organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


class TransferOwnershipBody(BaseModel):
    """Traspaso de propiedad (C2.2)."""

    #: Miembro **activo** que pasa a ser owner. Invitar y traspasar son cosas
    #: distintas: hacerlas de una convertiría un error de tipeo en el email en
    #: una organización cuyo owner no existe.
    nuevo_owner_user_id: int


class DeleteOrganizationBody(BaseModel):
    """Borrado de organización, con confirmación literal (C2.2)."""

    #: Hay que escribir `BORRAR`. Un botón no basta: la acción no tiene deshacer
    #: y se lleva trabajo de otras personas.
    confirmacion: str


class OrganizationDeletionSummary(BaseModel):
    """Qué se borró (o se borraría) con la organización.

    Es lo que la confirmación enseña **antes** de pedirla: «vas a borrar 14
    oportunidades y 37 comentarios» es una advertencia; «¿seguro?» no.

    Un `-1` significa que ese recuento no se pudo hacer, no que sea cero.
    """

    oportunidades: int = 0
    comentarios: int = 0
    miembros: int = 0


@router.post(
    "/organizations/{organization_id}/transfer-ownership",
    summary="Traspasar la propiedad de la organización",
    responses={
        403: {"description": "No sos el owner"},
        404: {"description": "El destinatario no es miembro activo"},
        409: {"description": "La organización personal no se traspasa"},
    },
)
async def post_transfer_ownership(
    organization_id: int,
    body: TransferOwnershipBody,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    """Mueve el rol `owner` a otro miembro (C2.2).

    Hasta 2026-09 no existía: `_guard_owner_row` lo reconocía en su propio
    docstring, y una organización cuyo owner se iba quedaba sin nadie que
    pudiera administrarla.

    El owner saliente queda como `admin`: quien monta un equipo no debería
    perder el acceso al traspasarlo.
    """
    try:
        await run_db(
            transferir_propiedad,
            organization_id=organization_id,
            actor_user_id=int(ctx["user_id"]),
            nuevo_owner_user_id=body.nuevo_owner_user_id,
        )
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationMemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrganizationLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StatusOk(status="ok")


@router.post(
    "/organizations/{organization_id}/leave",
    summary="Salir de la organización",
    responses={
        404: {"description": "No sos miembro"},
        409: {"description": "Sos el owner, o es tu organización personal"},
    },
)
async def post_leave_organization(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    """Salida voluntaria (C2.2).

    La membresía queda `revoked`, no borrada: un comentario firmado por alguien
    que ya no está sigue siendo suyo (ADR-030 §D).
    """
    try:
        await run_db(
            salir_de_organizacion,
            organization_id=organization_id,
            user_id=int(ctx["user_id"]),
        )
    except OrganizationMemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrganizationLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return StatusOk(status="ok")


@router.get(
    "/organizations/{organization_id}/deletion-preview",
    summary="Qué se borraría con la organización",
    responses={403: {"description": "No sos el owner"}},
)
async def get_deletion_preview(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationDeletionSummary:
    """El recuento que la confirmación tiene que enseñar antes de pedirla."""
    try:
        conteos = await run_db(
            resumen_de_borrado,
            organization_id=organization_id,
            actor_user_id=int(ctx["user_id"]),
        )
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return OrganizationDeletionSummary(**conteos)


@router.post(
    "/organizations/{organization_id}/delete",
    summary="Borrar la organización (confirmación literal)",
    responses={
        403: {"description": "No sos el owner"},
        404: {"description": "La organización no existe"},
        409: {"description": "Confirmación incorrecta, o es la personal"},
    },
)
async def post_delete_organization(
    organization_id: int,
    body: DeleteOrganizationBody,
    ctx: dict[str, Any] = Depends(require_recent_session()),
) -> OrganizationDeletionSummary:
    """Borra la organización y su dato corporativo (C2.2, ADR-030 §D).

    `POST /delete` y no `DELETE`: el borrado exige un cuerpo con la confirmación
    literal, y un `DELETE` con cuerpo lo tratan mal bastantes clientes y proxies.

    Exige además sesión reciente: se lleva trabajo de otras personas y no tiene
    deshacer.

    Qué cae con ella: **dato corporativo** — oportunidades, comentarios,
    capacidades, claves de organización. Qué sobrevive: el dato personal de cada
    miembro, que cuelga de su cuenta.
    """
    try:
        conteos = await run_db(
            borrar_organizacion,
            organization_id=organization_id,
            actor_user_id=int(ctx["user_id"]),
            confirmacion=body.confirmacion,
        )
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationMemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrganizationLifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return OrganizationDeletionSummary(**conteos)


@router.get(
    "/organizations/{organization_id}/members",
    response_model=list[OrganizationMembershipOut],
)
async def get_organization_members(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[OrganizationMembershipOut]:
    try:
        return await run_db(list_members, int(ctx["user_id"]), organization_id)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/organizations/invitations/accept",
    response_model=OrganizationSummary,
)
async def post_accept_organization_invitation(
    body: OrganizationInvitationAccept,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationSummary:
    """Canjea el enlace de invitación recibido por correo.

    Devuelve la organización a la que se acaba de entrar. El enlace es de un
    solo uso, caduca a los siete días y solo vale para la dirección a la que se
    envió.
    """
    try:
        return await run_db(
            accept_invitation_token,
            int(ctx["user_id"]),
            ctx.get("email"),
            body.token,
        )
    except OrganizationInvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/organizations/{organization_id}/members",
    response_model=OrganizationMembershipOut | OrganizationInvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_organization_member(
    organization_id: int,
    body: OrganizationMemberInvite,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationMembershipOut | OrganizationInvitationOut:
    """Incorpora a alguien al equipo por su correo.

    Si ya tiene cuenta activa, entra en el acto y la respuesta es su membresía.
    Si no la tiene, se crea una invitación pendiente, se le envía un enlace
    firmado y la respuesta es esa invitación: hasta 2026-09 este segundo caso
    respondía 404 y no había forma de incorporar a nadie que no se hubiera
    registrado antes por su cuenta.
    """
    try:
        return await run_db(
            invite_member_by_email,
            int(ctx["user_id"]),
            organization_id,
            str(body.email),
            body.role,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/organizations/{organization_id}/invitations",
    response_model=list[OrganizationInvitationOut],
)
async def get_organization_invitations(
    organization_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[OrganizationInvitationOut]:
    """Invitaciones pendientes del equipo.

    Restringido a owner y admin: son direcciones de correo de personas que
    todavía no pertenecen a la organización.
    """
    try:
        return await run_db(list_invitations, int(ctx["user_id"]), organization_id)
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/organizations/{organization_id}/invitations/{invitation_id}/resend",
    response_model=OrganizationInvitationOut,
)
async def post_resend_organization_invitation(
    organization_id: int,
    invitation_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationInvitationOut:
    """Vuelve a enviar el correo con un enlace nuevo; el anterior deja de valer."""
    try:
        return await run_db(resend_invitation, int(ctx["user_id"]), organization_id, invitation_id)
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationInvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/organizations/{organization_id}/invitations/{invitation_id}",
    response_model=StatusOk,
)
async def delete_organization_invitation(
    organization_id: int,
    invitation_id: int,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> StatusOk:
    """Anula una invitación pendiente sin borrar su rastro."""
    try:
        await run_db(revoke_invitation, int(ctx["user_id"]), organization_id, invitation_id)
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationInvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StatusOk(status="ok")


@router.put(
    "/organizations/{organization_id}/members/{member_user_id}",
    response_model=OrganizationMembershipOut,
)
async def put_organization_member(
    organization_id: int,
    member_user_id: int,
    body: OrganizationMembershipUpsert,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationMembershipOut:
    if body.user_id != member_user_id:
        raise HTTPException(status_code=422, detail="user_id no coincide con la ruta.")
    try:
        return await run_db(
            upsert_membership,
            int(ctx["user_id"]),
            organization_id,
            body,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post(
    "/pursuits",
    response_model=PursuitSummary,
    status_code=status.HTTP_201_CREATED,
)
async def post_pursuit(
    body: PursuitCreate,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
        max_length=200,
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitSummary:
    """Abre una oportunidad; reintentar la misma licitación no duplica.

    Abrirla es la señal de demanda más fuerte que existe, así que si el
    expediente no tiene ficha del pliego se lanza su extracción en background
    (``PLIEGO_FACTS_ON_PURSUIT``): quien acaba de comprometerse abrirá la
    pestaña Pliego hoy, no cuando el lote nocturno llegue a ese expediente.
    """
    try:
        pursuit, created = await run_db(
            create_pursuit,
            int(ctx["user_id"]),
            body,
            idempotency_key=idempotency_key,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if created:
        await _lanzar_ficha_si_falta(background, pursuit.licitacion_id, ctx)
    return pursuit


async def _lanzar_ficha_si_falta(
    background: BackgroundTasks, licitacion_id: str, ctx: dict[str, Any]
) -> None:
    """Encola la extracción de la ficha si no existe. Nunca falla la creación."""
    from config import settings

    if not settings.PLIEGO_FACTS_ON_PURSUIT:
        return
    try:
        from services.rag.fact_sheet import (
            get_fact_sheet,
            run_background_extraction,
            try_mark_extraction_running,
        )

        if await run_db(get_fact_sheet, licitacion_id) is not None:
            return
        if not await run_db(try_mark_extraction_running, licitacion_id):
            return
        raw_subject = ctx.get("user_key")
        background.add_task(
            run_background_extraction,
            licitacion_id,
            model=settings.PLIEGO_FACTS_MODEL,
            budget_subject=raw_subject if isinstance(raw_subject, str) and raw_subject else None,
        )
        log.info("pursuit_fact_sheet_extraction_started", licitacion_id=licitacion_id)
    except Exception as exc:
        log.warning(
            "pursuit_fact_sheet_extraction_skipped",
            licitacion_id=licitacion_id,
            error=str(exc)[:200],
        )


@router.get("/pursuits", response_model=PursuitListResponse)
async def get_pursuits(
    organization_id: int | None = Query(default=None, ge=1),
    pursuit_status: PursuitStatus | None = Query(default=None, alias="status"),
    responsible_user_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitListResponse:
    """Lista únicamente opportunities de una organización autorizada."""
    try:
        return await run_db(
            list_pursuits,
            int(ctx["user_id"]),
            organization_id=organization_id,
            status=pursuit_status,
            responsible_user_id=responsible_user_id,
            limit=limit,
            offset=offset,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/pursuits/metrics", response_model=PursuitMetrics)
async def get_pursuit_metrics(
    organization_id: int | None = Query(default=None, ge=1),
    period_from: datetime | None = Query(default=None),
    period_to: datetime | None = Query(default=None),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitMetrics:
    """Calcula funnel, win-rate, importe y tiempo de decisión."""
    try:
        return await run_db(
            get_metrics,
            int(ctx["user_id"]),
            organization_id=organization_id,
            period_from=period_from,
            period_to=period_to,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/pursuits/agenda", response_model=PipelineAgendaResponse)
async def get_pursuits_agenda(
    organization_id: int | None = Query(default=None, ge=1),
    solo_mios: bool = Query(
        default=False,
        description="Limita los pursuits a los que el usuario es responsable",
    ),
    tecnologia: str | None = Query(default=None, max_length=80),
    ccaa: str | None = Query(default=None, max_length=80),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PipelineAgendaResponse:
    """Agenda de compromisos: fusión, orden y bandas calculados en backend.

    Sin caché compartida: la respuesta es por usuario/organización (incluye el
    triaje de señales del propio usuario).
    """
    try:
        return await run_db(
            get_agenda,
            int(ctx["user_id"]),
            user_key=str(ctx["user_key"]),
            organization_id=organization_id,
            solo_mios=solo_mios,
            tecnologia=tecnologia,
            ccaa=ccaa,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# `/pursuits/tasks/agenda` se declara AQUÍ, antes de `/pursuits/{pursuit_id}`,
# y no junto al resto de rutas de tareas: FastAPI resuelve por orden de
# declaración, así que una ruta literal bajo `/pursuits/` que llegue después
# de la paramétrica nunca se alcanza — la petición entra por `{pursuit_id}`
# con el valor "tasks" y muere en un 422 que no dice nada.
@router.get("/pursuits/tasks/agenda", response_model=PursuitTaskAgendaResponse)
async def get_pursuit_tasks_agenda(
    organization_id: int | None = Query(default=None, ge=1),
    solo_mias: bool = Query(default=False, description="Sólo las asignadas a quien pregunta"),
    limite: int = Query(default=50, ge=1, le=500),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitTaskAgendaResponse:
    """Agenda del tablero: tareas pendientes de la organización por urgencia.

    Cada una trae el `id_externo` de su expediente: una lista de tareas que no
    dice de qué expediente son obliga a abrir cada una para saber si importa.
    """
    try:
        return await run_db(
            tasks_agenda,
            int(ctx["user_id"]),
            organization_id=organization_id,
            solo_mias=solo_mias,
            limite=limite,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/pursuits/baja-propia", response_model=BajaPropiaResult)
async def get_baja_propia(
    organization_id: int | None = Query(default=None, ge=1),
    segmento: str = Query("cpv", pattern="^(cpv|organo)$"),
    limite: int = Query(50, ge=1, le=200),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> BajaPropiaResult:
    """Mi baja media por CPV a cuatro dígitos o por órgano (C6.5).

    El mercado lo da `/competitive/bajas/referencia`; esto es la otra mitad, y
    hasta ahora no existía: el producto sabía cuánto baja el mercado y no cuánto
    baja el equipo que lo usa.

    Sólo cuenta lo **presentado** y con base sin IVA declarada (C1.1): comparar
    una oferta sin IVA contra un presupuesto que lo lleva produce una baja del
    21 % que no existió. Cada segmento declara su `n` y se ocultan los que no
    llegan al mínimo — con menos de cinco ofertas, la media la mueve un caso.
    """
    try:
        return await run_db(
            baja_propia,
            int(ctx["user_id"]),
            organization_id=organization_id,
            segmento=segmento,
            limite=limite,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/organizations/gonogo", response_model=GoNoGoAjustes)
async def get_gonogo_ajustes(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoAjustes:
    """Plantilla de go/no-go de la organización: pesos y umbral (C6.4, D30)."""
    try:
        pesos, umbral = await run_db(leer_ajustes_gonogo, int(ctx["user_id"]), organization_id)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return GoNoGoAjustes(pesos=GoNoGoPesos(**pesos), umbral=umbral)


@router.put(
    "/organizations/gonogo",
    response_model=GoNoGoAjustes,
    responses={
        403: {"description": "Sólo owner o admin"},
        422: {"description": "Los pesos no suman 100"},
    },
)
async def put_gonogo_ajustes(
    body: GoNoGoAjustes,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoAjustes:
    """Cambia los pesos y el umbral. Sólo owner/admin, y queda auditado.

    La plantilla decide contra qué se juzgan las oportunidades del equipo
    entero: quien la toca cambia el criterio de todos, así que el cambio deja
    rastro con el valor anterior y el nuevo.
    """
    try:
        pesos, umbral = await run_db(
            guardar_ajustes_gonogo,
            int(ctx["user_id"]),
            body.pesos.model_dump(),
            body.umbral,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except GoNoGoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GoNoGoAjustes(pesos=GoNoGoPesos(**pesos), umbral=umbral)


@router.get("/pursuits/weights-proposal", response_model=PesosPropuestos)
async def get_pursuits_weights_proposal(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PesosPropuestos:
    """Propone un ajuste de los pesos del Radar a partir de lo ganado y perdido.

    Compara, dimensión a dimensión, el desglose del score que tenían las
    oportunidades ganadas frente al de las perdidas: la dimensión que valía más
    en las ganadas sube y la que valía más en las perdidas baja, en una
    redistribución que sigue sumando 100.

    Sólo cuentan las oportunidades cerradas cuyo desglose quedó sellado al
    abrirlas. Por debajo del mínimo devuelve `estado: "insuficiente"` con su
    base, y ninguna propuesta: un ajuste sobre cuatro cierres no es evidencia.

    Es una propuesta. No se aplica sola.
    """
    try:
        return await run_db(
            get_weights_proposal,
            int(ctx["user_id"]),
            user_key=str(ctx["user_key"]),
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/pursuits/cartera",
    summary="Contratos ganados que siguen en ejecución (F4.3)",
    responses={403: {"description": "No perteneces a esa organización"}},
)
async def get_cartera(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[ContratoCartera]:
    """La cartera, con la ventana de relicitación de cada contrato.

    Se declara siempre de dónde sale la fecha de fin (`fecha_fin_origen`): una
    publicada por la fuente y una derivada de la duración no valen lo mismo en
    la pantalla donde se decide cuándo preparar una renovación.
    """

    try:
        return await run_db(
            cartera_de_usuario, int(ctx["user_id"]), organization_id=organization_id
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/pursuits/weights-proposal/apply", response_model=PesosPropuestosAplicados)
async def post_pursuits_weights_proposal_apply(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PesosPropuestosAplicados:
    """Aplica la propuesta vigente al perfil de scoring. Queda en el audit log.

    No admite pesos en el cuerpo: recalcula la propuesta y escribe exactamente
    esa, de modo que lo aplicado y lo que se enseñó no puedan divergir. El resto
    del perfil (keywords de afinidad, CPV, rango de importe) se conserva.

    Responde 422 mientras la propuesta sea insuficiente.
    """
    try:
        return await run_db(
            apply_weights_proposal,
            int(ctx["user_id"]),
            user_key=str(ctx["user_key"]),
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/pursuits/direccion",
    summary="Cuadro de mando de dirección (F4.2) — solo owner y admin",
    responses={403: {"description": "Dirección es para owner y admin"}},
)
async def get_direccion(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> CuadroDireccion:
    """El control de rol está **en el servicio**, no en el rail.

    Un `member` que teclee la URL recibe 403, no una pantalla sin enlace: un
    rail sin enlace es una sugerencia, esto es un permiso.
    """

    def _trabajo() -> CuadroDireccion:
        resuelta = exigir_direccion(int(ctx["user_id"]), organization_id)
        filas = _pursuit_repo.metric_rows(resuelta)
        return CuadroDireccion(
            organization_id=resuelta,
            win_rate_por_tecnologia=corte_con_minimo(filas, clave="tender_tecnologia"),
            win_rate_por_organo=corte_con_minimo(filas, clave="tender_organo"),
        )

    try:
        return await run_db(_trabajo)
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/pursuits/actividad",
    summary="Feed de lo que hizo el equipo (F4.5)",
    responses={403: {"description": "No perteneces a esa organización"}},
)
async def get_actividad(
    organization_id: int | None = Query(default=None, ge=1),
    antes_de_id: int | None = Query(
        default=None, ge=1, description="Cursor: id del último evento de la página anterior"
    ),
    usuario: int | None = Query(default=None, ge=1, description="Filtrar por quién lo hizo"),
    limit: int = Query(50, ge=1, le=200),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> FeedActividad:
    """Paginado **por cursor de id** y no por `offset`.

    El ledger es append-only, así que el id ya es el orden temporal; con
    `created_at` dos eventos del mismo segundo podrían repetirse o perderse
    entre páginas.

    Un `member` recibe el feed acotado a los eventos que puede ver, y la
    respuesta lo declara (`filtrado_por_rol`) en vez de dejarle creer que no
    ha pasado nada.
    """
    try:
        return await run_db(
            actividad_de_organizacion,
            int(ctx["user_id"]),
            organization_id=organization_id,
            antes_de_id=antes_de_id,
            solo_usuario=usuario,
            limit=limit,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


# Adjuntos propios de la oportunidad (C6.3). Las tres rutas que no cuelgan de
# `{pursuit_id}` van AQUÍ, delante de `/pursuits/{pursuit_id}`: FastAPI resuelve
# por orden de declaración, así que una literal bajo `/pursuits/` declarada
# después nunca se alcanza — la petición entra por la paramétrica con el valor
# "attachments" y muere en un 422 que no dice nada.
@router.get(
    "/pursuits/attachments/{attachment_id}/descarga",
    response_class=Response,
    summary="Descargar un adjunto propio con enlace firmado",
    responses={
        200: {"content": {"application/octet-stream": {}}, "description": "El fichero"},
        403: {"description": "Firma inválida o caducada"},
        404: {"description": "El adjunto ya no existe"},
    },
)
async def download_pursuit_attachment(
    attachment_id: int,
    exp: int = Query(..., description="Epoch de caducidad; va dentro de la firma"),
    sig: str = Query(..., max_length=400, description="Firma del par (adjunto, caducidad)"),
) -> Response:
    """Sirve el binario a quien traiga un enlace vigente.

    **Sin sesión a propósito.** El navegador tiene que poder pedir el fichero
    directamente, y una descarga que arrastra la cookie no es lo que se quiere.
    La autorización es la firma, que nombra el adjunto concreto y su caducidad:
    cambiar el `exp` de la URL invalida la firma en vez de alargar el permiso.

    403 y no 401 cuando ha caducado: no falta credencial, es que la que hay ya
    no vale, y ofrecer un `WWW-Authenticate` aquí sólo confundiría al cliente.
    """
    try:
        datos, filename, content_type = await run_db(
            descargar_adjunto, attachment_id, int(exp), sig
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AttachmentStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    # `filename*` en UTF-8: los nombres llevan tildes y `filename=` a secas los
    # entrega mojibake en Windows.
    disposicion = f"attachment; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=datos,
        media_type=content_type,
        headers={"Content-Disposition": disposicion},
    )


@router.put(
    "/pursuits/attachments/{attachment_id}/indexable",
    response_model=PursuitAttachmentOut,
    summary="Autorizar (o retirar) que el asistente lea un adjunto",
    responses={403: {"description": "No perteneces a esa organización"}, 404: {}},
)
async def put_pursuit_attachment_indexable(
    attachment_id: int,
    body: PursuitAttachmentIndexable,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitAttachmentOut:
    """Opt-in por fichero, nunca por organización.

    La decisión no es la misma para el DEUC —que no dice nada que el pliego no
    diga— que para la propuesta económica, y una preferencia de organización
    obligaría a tomarla una vez para las dos.
    """
    try:
        return await run_db(
            marcar_adjunto_indexable,
            int(ctx["user_id"]),
            attachment_id,
            indexable=body.indexable,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/pursuits/attachments/{attachment_id}",
    status_code=204,
    summary="Borrar un adjunto propio",
    responses={403: {"description": "No perteneces a esa organización"}, 404: {}},
)
async def delete_pursuit_attachment(
    attachment_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> Response:
    """Quita la fila y su objeto del bucket."""
    try:
        await run_db(
            borrar_adjunto,
            int(ctx["user_id"]),
            attachment_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AttachmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/pursuits/{pursuit_id}", response_model=PursuitDetail)
async def get_pursuit_detail(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitDetail:
    try:
        return await run_db(
            get_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/pursuits/{pursuit_id}/ficha.pdf",
    # `response_class`: la respuesta es el fichero, no un 200 JSON que
    # documentar. Mismo patrón que `api/routes/exports.py`.
    response_class=Response,
    summary="Ficha de la oportunidad en PDF (one-pager para dirección)",
    responses={
        200: {"content": {"application/pdf": {}}, "description": "El PDF"},
        403: {"description": "La oportunidad es de otra organización"},
        404: {"description": "No existe"},
    },
)
async def get_pursuit_ficha_pdf(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> Response:
    """F2.7 — el one-pager que se lleva a un comité.

    Va por la misma lectura con ámbito que `GET /pursuits/{id}`: un 403 aquí y
    un 403 allí son el mismo control, no dos.
    """
    try:
        pdf = await run_db(
            ficha_pdf,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            # `inline`: el usuario quiere verla antes de decidir si la guarda.
            "Content-Disposition": f'inline; filename="oportunidad-{pursuit_id}.pdf"',
        },
    )


class KitItemBody(BaseModel):
    """Marcado (o desmarcado) de un documento del kit."""

    clave: str = Field(min_length=1, max_length=120)
    listo: bool


@router.get(
    "/pursuits/{pursuit_id}/kit",
    summary="Kit de presentación: documentos que exige el pliego y cuáles están listos",
    responses={403: {"description": "La oportunidad es de otra organización"}},
)
async def get_pursuit_kit(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> KitPresentacion:
    """F2.3 — qué hay que entregar, en qué sobre, y qué falta."""
    try:
        return await run_db(
            kit_de_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/pursuits/{pursuit_id}/kit",
    status_code=status.HTTP_200_OK,
    summary="Marcar un documento del kit como listo (o desmarcarlo)",
    responses={403: {"description": "La oportunidad es de otra organización"}},
)
async def post_pursuit_kit_item(
    pursuit_id: int,
    body: KitItemBody,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> KitPresentacion:
    """Anota el marcado en el ledger y devuelve el kit ya actualizado.

    Devuelve el kit entero y no un `204`: el checklist es colaborativo, así que
    la respuesta es la ocasión de traer también lo que han marcado otros desde
    que el cliente lo cargó.
    """
    try:
        return await run_db(
            marcar_kit_de_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            clave=body.clave,
            listo=body.listo,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/pursuits/{pursuit_id}", response_model=PursuitDetail)
async def patch_pursuit(
    pursuit_id: int,
    body: PursuitUpdate,
    organization_id: int | None = Query(default=None, ge=1),
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
        max_length=200,
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitDetail:
    """Aplica una transición validada y añade un único evento."""
    try:
        return await run_db(
            update_pursuit,
            int(ctx["user_id"]),
            pursuit_id,
            body,
            organization_id=organization_id,
            idempotency_key=idempotency_key,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PursuitTransitionError, PursuitConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PursuitValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Hilo de comentarios ─────────────────────────────────────────────────────


@router.get("/pursuits/{pursuit_id}/comments", response_model=PursuitCommentListResponse)
async def get_pursuit_comments(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitCommentListResponse:
    """Conversación del equipo sobre la oportunidad.

    Paginada desde el más reciente (``offset=0`` = los últimos ``limit``), y
    cada página se devuelve en orden cronológico.
    """
    try:
        return await run_db(
            list_comments,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
            limit=limit,
            offset=offset,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/pursuits/{pursuit_id}/comments",
    response_model=PursuitCommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_pursuit_comment(
    pursuit_id: int,
    body: PursuitCommentCreate,
    organization_id: int | None = Query(default=None, ge=1),
    idempotency_key: str | None = Header(
        default=None,
        alias="X-Idempotency-Key",
        max_length=200,
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitCommentOut:
    """Publica un comentario; reintentar con la misma clave no lo duplica."""
    try:
        return await run_db(
            add_comment,
            int(ctx["user_id"]),
            pursuit_id,
            body,
            organization_id=organization_id,
            idempotency_key=idempotency_key,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete(
    "/pursuits/{pursuit_id}/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar un comentario",
)
async def delete_pursuit_comment(
    pursuit_id: int,
    comment_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    """Borra un comentario propio; owner y admin pueden borrar cualquiera."""
    try:
        await run_db(
            delete_comment,
            int(ctx["user_id"]),
            pursuit_id,
            comment_id,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (PursuitNotFoundError, PursuitCommentNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/pursuits/{pursuit_id}/attachments",
    response_model=PursuitAttachmentListResponse,
    summary="Adjuntos propios de la oportunidad (C6.3)",
    responses={403: {"description": "No perteneces a esa organización"}, 404: {}},
)
async def get_pursuit_attachments(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitAttachmentListResponse:
    """Lo que el equipo ha subido, más los límites que acepta subir.

    Los límites viajan en la respuesta para que el formulario pueda rechazar un
    fichero grande **antes** de subirlo, y no tras dos minutos de espera.
    """
    try:
        return await run_db(
            listar_adjuntos,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/pursuits/{pursuit_id}/attachments",
    response_model=PursuitAttachmentOut,
    status_code=201,
    summary="Subir un adjunto propio",
    responses={
        403: {"description": "No perteneces a esa organización"},
        404: {"description": "La oportunidad no existe en este espacio"},
        413: {"description": "El fichero supera el máximo"},
        415: {"description": "Tipo de fichero no admitido"},
        503: {"description": "No hay almacén de objetos configurado"},
    },
)
async def post_pursuit_attachment(
    pursuit_id: int,
    request: Request,
    filename: str = Query(..., max_length=200, description="Nombre con el que se descargará"),
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitAttachmentOut:
    """Guarda un documento del equipo junto a la oportunidad.

    **El cuerpo es el fichero en crudo**, con su tipo en `Content-Type` y su
    nombre en `?filename=`. No es `multipart/form-data` por una razón concreta:
    ese formato exige `python-multipart`, una dependencia de runtime que la API
    no declara hoy, y añadirla para subir un fichero por petición es pagar un
    paquete —y su superficie de parseo— por un sobre que aquí no lleva nada más.
    Un cuerpo binario es además lo que un `fetch(file)` manda sin envolver.

    El binario se lee entero en memoria a propósito: el tope son 25 MB, que cabe
    de sobra, y trocearlo obligaría a escribir en el bucket antes de saber si el
    fichero pasa los límites — o sea, a dejar basura cada vez que alguien
    arrastra el ZIP equivocado.

    Subir dos veces el mismo fichero no duplica nada: la clave del objeto es su
    huella y la fila tiene única `(pursuit_id, sha256)`.
    """
    contenido = await request.body()
    try:
        return await run_db(
            subir_adjunto,
            int(ctx["user_id"]),
            pursuit_id,
            contenido=contenido,
            filename=filename,
            content_type=request.headers.get("content-type", ""),
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AttachmentError as exc:
        # 413 y 415 dicen QUÉ límite se pasó; un 422 genérico obligaría a leer
        # el texto para saber si hay que comprimir o convertir.
        codigo = 413 if "bytes" in str(exc) else 415
        raise HTTPException(status_code=codigo, detail=str(exc)) from exc
    except AttachmentStoreError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post(
    "/pursuits/{pursuit_id}/attachments/{attachment_id}/enlace",
    response_model=PursuitAttachmentDownloadLink,
    summary="Enlace de descarga firmado y con caducidad",
    responses={403: {"description": "No perteneces a esa organización"}, 404: {}},
)
async def post_pursuit_attachment_link(
    pursuit_id: int,
    attachment_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitAttachmentDownloadLink:
    """Emite el enlace que la pestaña Expediente pone detrás del nombre.

    Se emite **con sesión** y se consume **sin ella**: aquí es donde se
    comprueba que quien pide pertenece a la organización dueña del adjunto, y
    por eso la descarga puede prescindir de la cookie.

    `POST` y no `GET` porque emitir una credencial de acceso —aunque dure quince
    minutos— no es una lectura: no debe cachearse ni quedarse en el historial.
    """
    usuario = int(ctx["user_id"])

    def _trabajo() -> tuple[str, int] | None:
        """Comprobación de pertenencia y firma, en UN salto al threadpool.

        La firma es HMAC —barata— pero carga las claves de firma la primera vez,
        y eso es I/O. Junto a la consulta va en el mismo salto: dos `await` para
        una operación que el usuario percibe como una sola son dos ventanas en
        las que el event loop puede quedarse esperando.
        """
        adjuntos = listar_adjuntos(usuario, pursuit_id, organization_id=organization_id)
        if not any(a.id == attachment_id for a in adjuntos.items):
            return None
        return firmar_descarga_adjunto(attachment_id)

    try:
        firmado = await run_db(_trabajo)
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if firmado is None:
        raise HTTPException(status_code=404, detail="El adjunto no existe en esta oportunidad.")

    token, expira = firmado
    ruta = f"/api/v1/pursuits/attachments/{attachment_id}/descarga"
    firma = quote(token, safe="")
    return PursuitAttachmentDownloadLink(url=f"{ruta}?exp={expira}&sig={firma}", expira=expira)


@router.get("/pursuits/{pursuit_id}/tasks", response_model=PursuitTaskListResponse)
async def get_pursuit_tasks(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    incluir_cerradas: bool = Query(
        default=True,
        description="Incluir las hechas y canceladas. Una cancelada dice que alguien lo evaluó.",
    ),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitTaskListResponse:
    """Tareas de la oportunidad: pendientes primero y por fecha de vencimiento.

    Hasta 2026-09 una oportunidad tenía **una** próxima acción y era texto
    libre. Preparar una oferta son diez tareas con responsables y fechas
    distintas (C6.1).
    """
    try:
        return await run_db(
            list_tasks,
            int(ctx["user_id"]),
            pursuit_id,
            organization_id=organization_id,
            incluir_cerradas=incluir_cerradas,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/pursuits/{pursuit_id}/tasks",
    response_model=PursuitTaskOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_pursuit_task(
    pursuit_id: int,
    body: PursuitTaskCreate,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitTaskOut:
    """Crea una tarea y actualiza la próxima acción del expediente.

    `next_action` deja de escribirse a mano: pasa a ser la tarea pendiente más
    próxima a vencer. Un campo que hay que mantener sincronizado a mano se
    desincroniza, y el tablero acaba enseñando algo que se terminó hace
    semanas.
    """
    try:
        return await run_db(
            add_task,
            int(ctx["user_id"]),
            pursuit_id,
            body,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch(
    "/pursuits/{pursuit_id}/tasks/{task_id}",
    response_model=PursuitTaskOut,
    responses={404: {"description": "La tarea no existe en este espacio"}},
)
async def patch_pursuit_task(
    pursuit_id: int,
    task_id: int,
    body: PursuitTaskUpdate,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitTaskOut:
    """Cambia una tarea: título, responsable, fecha o estado.

    Los campos ausentes no se tocan; los enviados a `null` sí borran el valor —
    así se puede desasignar una tarea o quitarle el plazo.
    """
    try:
        return await run_db(
            update_task,
            int(ctx["user_id"]),
            pursuit_id,
            task_id,
            body,
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitTaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put(
    "/pursuits/{pursuit_id}/gonogo",
    response_model=GoNoGoResult,
    responses={
        404: {"description": "La oportunidad no existe en este espacio"},
        422: {"description": "Faltan criterios o están fuera de 1-5"},
    },
)
async def put_pursuit_gonogo(
    pursuit_id: int,
    body: GoNoGoPuntuaciones,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoResult:
    """Puntúa la oportunidad con la plantilla vigente (C6.4, D30).

    Hasta 2026-09 la decisión más cara del proceso —presentarse o no— se
    registraba como una etiqueta y un párrafo de texto libre, así que «¿en qué
    nos equivocamos al decidir?» no tenía respuesta: no constaba contra qué se
    decidió.

    El total se calcula con los pesos de **este momento** y se guarda. Los pesos
    cambian; recalcularlo al leer haría que cambiar uno reescribiera decisiones
    ya tomadas.
    """
    try:
        datos = await run_db(
            puntuar_gonogo,
            int(ctx["user_id"]),
            pursuit_id,
            body.model_dump(),
            organization_id=organization_id,
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except GoNoGoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GoNoGoResult(
        pursuit_id=datos["pursuit_id"],
        puntuaciones=GoNoGoPuntuaciones(**datos["puntuaciones"]),
        total=datos["total"],
        umbral=datos["umbral"],
        bajo_umbral=datos["bajo_umbral"],
    )
