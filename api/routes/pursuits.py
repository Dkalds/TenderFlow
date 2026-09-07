"""API colaborativa de organizaciones y oportunidades."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth, require_recent_session
from observability.logging import get_logger
from services.organizations import (
    OrganizationAccessError,
    OrganizationLifecycleError,
    OrganizationMemberNotFoundError,
    OrganizationPermissionError,
    add_member_by_email,
    borrar_organizacion,
    create_organization,
    get_active_organization,
    list_members,
    list_organizations,
    resumen_de_borrado,
    salir_de_organizacion,
    transferir_propiedad,
    upsert_membership,
)
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
    PursuitConflictError,
    PursuitNotFoundError,
    PursuitTransitionError,
    PursuitValidationError,
    baja_propia,
    create_pursuit,
    get_agenda,
    get_metrics,
    get_pursuit,
    list_pursuits,
    update_pursuit,
)
from shared.dto import (
    BajaPropiaResult,
    OrganizationCreate,
    OrganizationMemberInvite,
    OrganizationMembershipOut,
    OrganizationMembershipUpsert,
    OrganizationSummary,
    PipelineAgendaResponse,
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
    "/organizations/{organization_id}/members",
    response_model=OrganizationMembershipOut,
    status_code=status.HTTP_201_CREATED,
)
async def post_organization_member(
    organization_id: int,
    body: OrganizationMemberInvite,
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> OrganizationMembershipOut:
    """Incorpora por correo a un usuario ya registrado. No crea invitaciones
    para correos sin cuenta: el alta requiere que la persona se registre.
    """
    try:
        return await run_db(
            add_member_by_email,
            int(ctx["user_id"]),
            organization_id,
            str(body.email),
            body.role,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationMemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


# ── Tareas de la oportunidad (C6.1) ──────────────────────────────────────────


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
