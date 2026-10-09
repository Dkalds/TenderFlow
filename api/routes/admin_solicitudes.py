"""Admin endpoints — cola de solicitudes de acceso llegadas desde la landing.

Requiere autenticación dual (sesión o API key) + is_admin, como el resto de
``/admin``. El recorrido entero se hace desde aquí (RFC 242): ver la cola,
**conceder** el acceso —``conceder`` en el PATCH escribe una concesión en
``access_grants``, por email o por dominio—, avisar a la persona, revocar una
concesión y descartar. ``OAUTH_ALLOWED_EMAILS``/``OAUTH_ALLOWED_DOMAINS`` siguen
siendo el arranque estático: no se editan para un alta normal y no se pueden
revocar desde aquí.

**El aviso a la persona** no es un efecto del cambio de estado a secas. Al
conceder, el correo sale después de persistir la concesión. Con ``notificar``
y sin ``conceder`` solo sale si esa dirección ya entra —lista estática o
concesión previa, con la misma comprobación que decide el login—: prometerle a
alguien un acceso que le daría ``email_not_allowed`` es peor que no escribirle.

La auditoría (``solicitud_acceso.estado``, ``access_grant.granted``,
``access_grant.revoked``) se escribe con ``log_event`` una vez confirmada la
escritura y es best-effort, como en todo el producto: no comparte transacción
con la concesión.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.concurrency import run_db, run_io
from api.routes.auth import _oauth_access_allowed
from api.routes.dual_auth import require_admin
from db.access_grants import (
    AccessGrantKind,
    ConcesionInvalida,
    grant_access_request,
    list_access_grants,
    revoke_access,
)
from db.audit import log_event
from db.solicitudes_acceso import (
    ESTADOS,
    actualizar_estado,
    listar_solicitudes,
    obtener_solicitud,
)
from observability.logging import get_logger
from services.solicitudes_acceso import notificar_acceso_concedido
from shared.audit_events import (
    ACCESS_GRANT_GRANTED,
    ACCESS_GRANT_REVOKED,
    SOLICITUD_ACCESO_ESTADO,
)

log = get_logger(__name__)

router = APIRouter(prefix="/admin/solicitudes-acceso", tags=["admin"])


class SolicitudAccesoOut(BaseModel):
    """Una solicitud de la cola, tal como la ve el panel."""

    id: int
    email: str
    empresa: str | None = None
    mensaje: str | None = None
    origen: str | None = None
    estado: str
    created_at: datetime | None = None


class EstadoBody(BaseModel):
    estado: str
    conceder: Literal["email", "domain"] | None = None
    #: Escribir a quien pidió el acceso diciéndole que ya puede entrar.
    #:
    #: ``conceder`` ya lo implica: una concesión avisa siempre. Este campo es
    #: para avisar **sin** conceder, y por sí solo no habilita a nadie: el
    #: correo sale solo si la dirección ya pasa la allowlist (estática o
    #: dinámica). Si no la pasa no se envía y la respuesta lleva
    #: ``notificado: false``, porque mandaría a la persona contra un
    #: ``email_not_allowed``. Se ignora si el estado no es ``atendida``.
    notificar: bool = False


class CambioEstadoOut(BaseModel):
    """Resultado del cambio de estado.

    Conserva ``status`` para no romper a quien ya lo lea, y añade si el correo
    salió. Sin ese campo, un SMTP mal configurado dejaría al operador creyendo
    que ha avisado a alguien a quien nadie escribió — el mismo fallo silencioso
    que este endpoint viene a cerrar, una capa más arriba.

    ``notificado`` es ``None`` cuando no se pidió aviso: distinto de ``False``,
    que significa "se pidió y no salió".
    """

    status: str = "ok"
    notificado: bool | None = None
    grant_id: int | None = None


class AccessGrantOut(BaseModel):
    id: int
    kind: AccessGrantKind
    value: str
    active: bool
    granted_by: int | None = None
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None


def _id_del_admin(admin: dict[str, Any]) -> int | None:
    """``users.id`` de quien actúa, para ``audit_log.user_id`` (ADR-030 §D).

    Sin él la fila se guardaba con ``user_id`` NULL y la identidad del actor
    quedaba solo como texto, en la columna que rellena ``actor``.
    """
    valor = admin.get("user_id")
    return int(valor) if valor is not None else None


@router.get("", response_model=list[SolicitudAccesoOut])
async def listar(
    estado: str | None = Query(None, description="Filtra por estado de la cola"),
    limit: int = Query(100, ge=1, le=500),
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[SolicitudAccesoOut]:
    if estado is not None and estado not in ESTADOS:
        raise HTTPException(status_code=422, detail=f"estado no válido: {estado}")
    filas = await run_db(listar_solicitudes, estado=estado, limit=limit)
    return [SolicitudAccesoOut(**fila) for fila in filas]


@router.patch("/{solicitud_id}", response_model=CambioEstadoOut)
async def cambiar_estado(
    solicitud_id: int,
    body: EstadoBody,
    admin: dict[str, Any] = Depends(require_admin),
) -> CambioEstadoOut:
    if body.estado not in ESTADOS:
        raise HTTPException(status_code=422, detail=f"estado no válido: {body.estado}")

    if body.conceder is not None and body.estado != "atendida":
        raise HTTPException(status_code=422, detail="Solo se concede una solicitud atendida")
    avisar = (body.notificar or body.conceder is not None) and body.estado == "atendida"

    def _trabajo() -> tuple[bool, dict[str, Any] | None, int | None]:
        # El cambio de estado y su registro de auditoría son dos escrituras
        # síncronas: van juntas en un único salto al threadpool. Dejar el
        # `log_event` fuera bloqueaba el event loop —y con él, todos los demás
        # endpoints del proceso— mientras escribía.
        #
        # La lectura previa sólo ocurre si hay que avisar: hace falta la
        # dirección, y también el estado anterior para no reenviar el correo a
        # quien ya estaba atendido (pulsar dos veces no puede escribir dos veces
        # a la misma persona).
        grant_id: int | None = None
        previa: dict[str, Any] | None
        if body.conceder is not None:
            granted = grant_access_request(
                solicitud_id,
                body.conceder,
                granted_by=int(admin["user_id"]),
            )
            if granted is None:
                return False, None, None
            previa = {
                "email": granted["email"],
                "empresa": granted["empresa"],
                "estado": granted["previous_state"],
            }
            actualizada = True
            grant = granted["grant"]
            grant_id = grant["id"]
        else:
            previa = obtener_solicitud(solicitud_id) if avisar else None
            actualizada = actualizar_estado(solicitud_id, body.estado)
        if actualizada:
            log_event(
                event_type=SOLICITUD_ACCESO_ESTADO,
                actor=str(admin.get("user_id", "")),
                user_id=_id_del_admin(admin),
                resource=f"solicitud_acceso:{solicitud_id}",
                detail=body.estado,
            )
            if body.conceder is not None:
                log_event(
                    event_type=ACCESS_GRANT_GRANTED,
                    actor=str(admin.get("user_id", "")),
                    user_id=_id_del_admin(admin),
                    resource=f"access_grant:{grant_id}",
                    detail={"kind": grant["kind"]},
                )
        return actualizada, previa, grant_id

    try:
        actualizada, previa, grant_id = await run_db(_trabajo)
    except ConcesionInvalida as exc:
        # Solo la lanza `grant_access_request`, y antes de escribir: la
        # transacción se deshace, así que no hay concesión ni cambio de estado
        # que auditar. Su mensaje está escrito para el administrador («concede
        # el email»); sin esta traducción caía en el manejador global de
        # `ValueError`, que responde un 400 sin motivo.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not actualizada:
        raise HTTPException(status_code=404, detail="solicitud no encontrada")

    if not avisar:
        return CambioEstadoOut(status="ok", grant_id=grant_id)

    if previa is None or previa.get("estado") == "atendida":
        # Ya estaba atendida (o desapareció entre la lectura y la escritura): el
        # estado queda bien, pero no se reenvía nada.
        return CambioEstadoOut(status="ok", notificado=False, grant_id=grant_id)

    email = str(previa.get("email") or "")
    if body.conceder is None and not await _oauth_access_allowed(email):
        # `notificar` sin `conceder` no habilita a nadie. Se pregunta con la
        # misma función que decide el login, no con una copia: si el callback
        # rechazaría esta dirección, el correo «ya tienes acceso» sería
        # mentira. El estado ya quedó cambiado; lo que no sale es el aviso, y
        # la respuesta lo dice (`notificado: false`). Al conceder no hace falta
        # preguntar: la concesión se acaba de escribir en esta misma petición.
        log.info("solicitud_acceso_aviso_sin_acceso", solicitud_id=solicitud_id)
        return CambioEstadoOut(status="ok", notificado=False, grant_id=grant_id)

    # El correo va fuera del `run_db`: es I/O de red con su propio timeout, y
    # meterlo en el salto de base de datos retendría una conexión del pool
    # mientras habla un SMTP.
    empresa_valor = previa.get("empresa")
    empresa = str(empresa_valor) if empresa_valor else None
    notificado = await run_io(notificar_acceso_concedido, email=email, empresa=empresa)
    return CambioEstadoOut(status="ok", notificado=notificado, grant_id=grant_id)


@router.get("/grants", response_model=list[AccessGrantOut])
async def listar_grants(
    include_inactive: bool = Query(False),
    _admin: dict[str, Any] = Depends(require_admin),
) -> list[AccessGrantOut]:
    rows = await run_db(list_access_grants, include_inactive=include_inactive)
    return [AccessGrantOut.model_validate(row) for row in rows]


@router.delete("/grants/{grant_id}", response_model=AccessGrantOut)
async def revocar_grant(
    grant_id: int,
    admin: dict[str, Any] = Depends(require_admin),
) -> AccessGrantOut:
    grant = await run_db(revoke_access, grant_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="concesión no encontrada o ya revocada")
    await run_db(
        log_event,
        event_type=ACCESS_GRANT_REVOKED,
        actor=str(admin.get("user_id", "")),
        user_id=_id_del_admin(admin),
        resource=f"access_grant:{grant_id}",
        detail={"kind": grant["kind"]},
    )
    return AccessGrantOut.model_validate(grant)
