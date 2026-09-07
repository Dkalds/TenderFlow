"""API colaborativa de organizaciones y oportunidades."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

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
from services.pursuits import (
    PursuitConflictError,
    PursuitNotFoundError,
    PursuitTransitionError,
    PursuitValidationError,
    create_pursuit,
    get_agenda,
    get_metrics,
    get_pursuit,
    list_pursuits,
    update_pursuit,
)
from shared.dto import (
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
    PursuitUpdate,
    StatusOk,
)

log = get_logger(__name__)
router = APIRouter(tags=["pursuits"])


# ── DTOs de captura: tareas, go/no-go y «mi baja» (C6) ──────────────────────
#
# Van arriba, junto al router, y no al lado de sus rutas: los `response_model`
# se evalúan al importar el módulo, así que una clase declarada después de la
# ruta que la usa rompe el import con un NameError.


class PursuitTaskCreate(BaseModel):
    """Alta de una tarea. `vence` es `YYYY-MM-DD` o ausente."""

    titulo: str = Field(..., min_length=1, max_length=300)
    responsable_user_id: int | None = Field(default=None, ge=1)
    vence: str | None = Field(default=None, max_length=10)


class PursuitTaskPatch(BaseModel):
    """Cambios sobre una tarea. Ausente = no tocar.

    `limpiar_responsable` y `limpiar_vence` existen porque `null` ya significa
    «no tocar»: sin ellos, quitarle la fecha a una tarea sería imposible, o bien
    no mandarla la borraría sin querer.
    """

    titulo: str | None = Field(default=None, min_length=1, max_length=300)
    responsable_user_id: int | None = Field(default=None, ge=1)
    vence: str | None = Field(default=None, max_length=10)
    estado: str | None = Field(
        default=None, description="pendiente | en_curso | hecha | descartada"
    )
    limpiar_responsable: bool = False
    limpiar_vence: bool = False


class PursuitTaskOut(BaseModel):
    id: int
    pursuit_id: int
    organization_id: int
    titulo: str
    responsable_user_id: int | None = None
    responsable_name: str | None = None
    vence: str | None = None
    estado: str
    created_at: str
    updated_at: str


class GoNoGoCriterioOut(BaseModel):
    criterio: str
    etiqueta: str
    invertido: bool
    peso: float | None = None
    puntuacion: int | None = None
    motivo: str | None = None
    author_name: str | None = None


class GoNoGoWeightsOut(BaseModel):
    organization_id: int
    umbral: float
    criterios: list[GoNoGoCriterioOut]


class GoNoGoWeightsIn(BaseModel):
    """Pesos por criterio. Los ausentes conservan su valor guardado."""

    pesos: dict[str, float]


class GoNoGoScoreIn(BaseModel):
    criterio: str
    puntuacion: int = Field(..., ge=1, le=5)
    motivo: str | None = Field(default=None, max_length=1000)


class GoNoGoScoreOut(BaseModel):
    pursuit_id: int
    organization_id: int
    criterios: list[GoNoGoCriterioOut]
    total: float
    umbral: float
    recomendacion: str
    criterios_puntuados: int
    completa: bool
    decision: str | None = None
    discrepa: bool


class MiBajaSegmento(BaseModel):
    segmento: str
    clave: str
    n: int
    baja_propia_pct: float | None = None
    baja_mercado_pct: float | None = None
    contratos_mercado: int
    suficiente: bool
    delta_pct: float | None = None


class MiBajaOut(BaseModel):
    organization_id: int
    base: str
    ofertas_consideradas: int
    segmentos: list[MiBajaSegmento]


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


# ── Rutas estáticas bajo /pursuits ───────────────────────────────────────────
#
# Van **antes** de `/pursuits/{pursuit_id}` a propósito: FastAPI resuelve por
# orden de declaración, así que declaradas después, `GET /pursuits/mi-baja`
# entraría por el detalle con `pursuit_id="mi-baja"` y devolvería un 422 que no
# dice nada. Es el mismo motivo por el que `/pursuits/metrics` y
# `/pursuits/agenda` están donde están. `tests/test_c6_captura.py` fija el orden
# para que un añadido futuro no lo rompa en silencio.


@router.get("/pursuits/tasks/agenda", response_model=list[PursuitTaskOut])
async def get_tasks_agenda(
    organization_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[PursuitTaskOut]:
    """Tareas abiertas de la organización por urgencia (Mi Pipeline → Agenda)."""
    from services.pursuit_tasks import agenda

    try:
        filas = await run_db(
            agenda, int(ctx["user_id"]), organization_id=organization_id, limit=limit
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return [PursuitTaskOut.model_validate(f) for f in filas]


# ── Plantilla go/no-go (C6.4, D30) ───────────────────────────────────────────


@router.get("/pursuits/mi-baja", response_model=MiBajaOut)
async def get_mi_baja(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> MiBajaOut:
    """Mi baja media por CPV4 y por órgano, frente a la del mercado.

    `suficiente` dice si el segmento llega a las cinco ofertas que el ítem
    exige; los que no llegan salen igual **con su `n`**, porque saber que solo
    hay dos es información y no saberlo es lo que engaña.
    """
    from services.mi_baja import mi_baja

    try:
        return MiBajaOut.model_validate(
            await run_db(mi_baja, int(ctx["user_id"]), organization_id=organization_id)
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


@router.get("/pursuits/{pursuit_id}/tasks", response_model=list[PursuitTaskOut])
async def get_pursuit_tasks(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> list[PursuitTaskOut]:
    """Tareas de la oportunidad: abiertas primero y por vencimiento."""
    from services.pursuit_tasks import list_tasks

    try:
        filas = await run_db(
            list_tasks, int(ctx["user_id"]), pursuit_id, organization_id=organization_id
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [PursuitTaskOut.model_validate(f) for f in filas]


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
    """Crea una tarea y recalcula `next_action`, que pasa a derivarse de estas."""
    from services.pursuit_tasks import create_task

    try:
        fila = await run_db(
            create_task,
            int(ctx["user_id"]),
            pursuit_id,
            titulo=body.titulo,
            responsable_user_id=body.responsable_user_id,
            vence=body.vence,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PursuitTaskOut.model_validate(fila)


@router.patch("/pursuits/{pursuit_id}/tasks/{task_id}", response_model=PursuitTaskOut)
async def patch_pursuit_task(
    pursuit_id: int,
    task_id: int,
    body: PursuitTaskPatch,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> PursuitTaskOut:
    from services.pursuit_tasks import PursuitTaskNotFoundError, update_task

    try:
        fila = await run_db(
            update_task,
            int(ctx["user_id"]),
            pursuit_id,
            task_id,
            organization_id=organization_id,
            titulo=body.titulo,
            responsable_user_id=body.responsable_user_id,
            vence=body.vence,
            estado=body.estado,
            limpiar_responsable=body.limpiar_responsable,
            limpiar_vence=body.limpiar_vence,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (PursuitNotFoundError, PursuitTaskNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return PursuitTaskOut.model_validate(fila)


@router.delete(
    "/pursuits/{pursuit_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_pursuit_task(
    pursuit_id: int,
    task_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> None:
    from services.pursuit_tasks import PursuitTaskNotFoundError, delete_task

    try:
        await run_db(
            delete_task,
            int(ctx["user_id"]),
            pursuit_id,
            task_id,
            organization_id=organization_id,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (PursuitNotFoundError, PursuitTaskNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/organizations/go-no-go/weights", response_model=GoNoGoWeightsOut)
async def get_go_no_go_weights(
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoWeightsOut:
    from services.go_no_go import get_weights

    try:
        return GoNoGoWeightsOut.model_validate(
            await run_db(get_weights, int(ctx["user_id"]), organization_id=organization_id)
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.put("/organizations/go-no-go/weights", response_model=GoNoGoWeightsOut)
async def put_go_no_go_weights(
    body: GoNoGoWeightsIn,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoWeightsOut:
    """Cambia los pesos de la plantilla. Solo owner/admin; queda auditado."""
    from services.go_no_go import set_weights

    try:
        return GoNoGoWeightsOut.model_validate(
            await run_db(
                set_weights, int(ctx["user_id"]), body.pesos, organization_id=organization_id
            )
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/pursuits/{pursuit_id}/go-no-go", response_model=GoNoGoScoreOut)
async def get_pursuit_go_no_go(
    pursuit_id: int,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoScoreOut:
    """Puntuación ponderada de la oportunidad y si contradice la decisión tomada."""
    from services.go_no_go import get_score

    try:
        return GoNoGoScoreOut.model_validate(
            await run_db(
                get_score, int(ctx["user_id"]), pursuit_id, organization_id=organization_id
            )
        )
    except OrganizationAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/pursuits/{pursuit_id}/go-no-go", response_model=GoNoGoScoreOut)
async def put_pursuit_go_no_go(
    pursuit_id: int,
    body: GoNoGoScoreIn,
    organization_id: int | None = Query(default=None, ge=1),
    ctx: dict[str, Any] = Depends(require_any_auth),
) -> GoNoGoScoreOut:
    from services.go_no_go import set_score

    try:
        return GoNoGoScoreOut.model_validate(
            await run_db(
                set_score,
                int(ctx["user_id"]),
                pursuit_id,
                criterio=body.criterio,
                puntuacion=body.puntuacion,
                motivo=body.motivo,
                organization_id=organization_id,
            )
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except PursuitNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ── Mi baja frente al mercado (C6.5) ─────────────────────────────────────────
