"""Rutas de organizaciones: alta, miembros, invitaciones y ciclo de vida.

Vivían en ``api/routes/pursuits.py`` (2.100 líneas) por historia: las
oportunidades fueron la primera superficie colaborativa y la organización
nació a su lado. No comparten nada con las rutas de oportunidades salvo la
dependencia de autenticación, y salen aquí por la regla de módulos-dios del
backlog. La configuración de producto de la organización sigue aparte, en
``api/routes/organization_settings.py``.

El ``tag`` sigue siendo ``pursuits`` para no cambiar el contrato OpenAPI ni el
cliente generado.
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth, require_recent_session
from db.audit import log_event
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
from shared.audit_events import (
    ORG_CREATED,
    ORG_DELETED,
    ORG_INVITATION_ACCEPTED,
    ORG_INVITATION_RESENT,
    ORG_INVITATION_REVOKED,
    ORG_INVITATION_SENT,
    ORG_LEFT,
    ORG_MEMBER_ADDED,
    ORG_MEMBER_REMOVED,
    ORG_MEMBER_ROLE_CHANGED,
    ORG_OWNERSHIP_TRANSFERRED,
)
from shared.dto import (
    OrganizationCreate,
    OrganizationInvitationAccept,
    OrganizationInvitationOut,
    OrganizationMemberInvite,
    OrganizationMembershipOut,
    OrganizationMembershipUpsert,
    OrganizationSummary,
    StatusOk,
)

router = APIRouter(tags=["pursuits"])


async def _auditar_organizacion(
    ctx: dict[str, Any], event_type: str, organization_id: int, **detail: Any
) -> None:
    """Deja el rastro de un evento ``org.*`` (``shared/audit_events.py``).

    ``resource="org:<id>"`` es lo que ``GET /organizations/{id}/audit``
    recupera; el actor va como ``users.id`` y el ``detail`` solo lleva ids,
    nunca correos (ADR-030 §D). ``log_event`` no lanza: la auditoría no rompe
    la petición que acaba de completarse.
    """
    await run_db(
        log_event,
        event_type=event_type,
        user_id=int(ctx["user_id"]),
        resource=f"org:{organization_id}",
        detail={"organization_id": organization_id, **detail},
    )


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
    creada = await run_db(create_organization, int(ctx["user_id"]), body.name)
    await _auditar_organizacion(ctx, ORG_CREATED, creada.id)
    return creada


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
    #: Ficheros subidos a las oportunidades: lo único de la lista que además
    #: vive fuera de Postgres. El repositorio lo contaba y este modelo lo
    #: tiraba sin decir nada, así que la advertencia callaba justo los
    #: documentos del equipo que se van con la organización.
    adjuntos: int = 0


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
    await _auditar_organizacion(
        ctx,
        ORG_OWNERSHIP_TRANSFERRED,
        organization_id,
        from_user_id=int(ctx["user_id"]),
        to_user_id=body.nuevo_owner_user_id,
    )
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
    await _auditar_organizacion(ctx, ORG_LEFT, organization_id, user_id=int(ctx["user_id"]))
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
    # El rastro sobrevive a la organización: es el único sitio donde queda
    # cuánto se llevó el borrado, ahora que las filas ya no están.
    await _auditar_organizacion(ctx, ORG_DELETED, organization_id, **conteos)
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
        organizacion = await run_db(
            accept_invitation_token,
            int(ctx["user_id"]),
            ctx.get("email"),
            body.token,
        )
    except OrganizationInvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrganizationPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    await _auditar_organizacion(
        ctx, ORG_INVITATION_ACCEPTED, organizacion.id, user_id=int(ctx["user_id"])
    )
    return organizacion


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
        resultado = await run_db(
            invite_member_by_email,
            int(ctx["user_id"]),
            organization_id,
            str(body.email),
            body.role,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    # Dos eventos distintos porque son dos hechos distintos: una persona que
    # ya está dentro, o un enlace que todavía tiene que canjearse. En ninguno
    # va el correo: el id de la invitación es lo que enlaza con ella.
    if isinstance(resultado, OrganizationInvitationOut):
        await _auditar_organizacion(
            ctx,
            ORG_INVITATION_SENT,
            organization_id,
            invitation_id=resultado.id,
            role=resultado.role,
        )
    else:
        await _auditar_organizacion(
            ctx, ORG_MEMBER_ADDED, organization_id, user_id=resultado.user_id, role=resultado.role
        )
    return resultado


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
        reenviada = await run_db(
            resend_invitation, int(ctx["user_id"]), organization_id, invitation_id
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationInvitationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _auditar_organizacion(
        ctx,
        ORG_INVITATION_RESENT,
        organization_id,
        invitation_id=reenviada.id,
        previous_invitation_id=invitation_id,
    )
    return reenviada


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
    await _auditar_organizacion(
        ctx, ORG_INVITATION_REVOKED, organization_id, invitation_id=invitation_id
    )
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
        membresia = await run_db(
            upsert_membership,
            int(ctx["user_id"]),
            organization_id,
            body,
        )
    except (OrganizationAccessError, OrganizationPermissionError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except OrganizationMemberNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # Un upsert que deja la membresía fuera de `active` es una baja, aunque la
    # ruta sea la misma: el rastro lo nombra como tal.
    evento = ORG_MEMBER_ROLE_CHANGED if body.status == "active" else ORG_MEMBER_REMOVED
    await _auditar_organizacion(
        ctx,
        evento,
        organization_id,
        user_id=member_user_id,
        role=membresia.role,
        status=membresia.status,
    )
    return membresia
