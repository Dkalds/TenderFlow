"""Admin endpoints — cola de solicitudes de acceso llegadas desde la landing.

Requiere autenticación dual (sesión o API key) + is_admin, como el resto de
``/admin``. Aprobar una solicitud **no** se hace desde aquí: la allowlist de
acceso vive en ``OAUTH_ALLOWED_EMAILS``/``OAUTH_ALLOWED_DOMAINS`` y sigue
siendo una decisión de operación. Lo que da esta cola es saber que la petición
existe y poder marcarla como atendida o descartada.

Lo que sí se cierra desde aquí es **el aviso a la persona**: hasta ahora nadie
le escribía nunca, aunque la página de gracias le promete que "la respuesta
llega por correo". El correo es **opt-in por operación** (``notificar``) y no un
efecto automático del cambio de estado, porque el sistema no puede saber si la
allowlist ya se editó: enviarlo solo cuando el operador lo pide es lo que evita
prometerle a alguien un acceso que todavía le daría 403.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.concurrency import run_db, run_io
from api.routes.dual_auth import require_admin
from db.audit import log_event
from db.solicitudes_acceso import (
    ESTADOS,
    actualizar_estado,
    listar_solicitudes,
    obtener_solicitud,
)
from observability.logging import get_logger
from services.solicitudes_acceso import notificar_acceso_concedido

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
    #: Escribir a quien pidió el acceso diciéndole que ya puede entrar.
    #:
    #: Opt-in y no automático: sólo el operador sabe si ya añadió la dirección a
    #: ``OAUTH_ALLOWED_EMAILS``/``OAUTH_ALLOWED_DOMAINS``. Un correo enviado
    #: antes de eso manda a la persona contra un 403, que es peor que no
    #: escribirle. Se ignora si el estado no es ``atendida``.
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

    avisar = body.notificar and body.estado == "atendida"

    def _trabajo() -> tuple[bool, dict[str, Any] | None]:
        # El cambio de estado y su registro de auditoría son dos escrituras
        # síncronas: van juntas en un único salto al threadpool. Dejar el
        # `log_event` fuera bloqueaba el event loop —y con él, todos los demás
        # endpoints del proceso— mientras escribía.
        #
        # La lectura previa sólo ocurre si hay que avisar: hace falta la
        # dirección, y también el estado anterior para no reenviar el correo a
        # quien ya estaba atendido (pulsar dos veces no puede escribir dos veces
        # a la misma persona).
        previa = obtener_solicitud(solicitud_id) if avisar else None
        actualizada = actualizar_estado(solicitud_id, body.estado)
        if actualizada:
            log_event(
                event_type="solicitud_acceso.estado",
                user_key=str(admin.get("user_id", "")),
                resource=f"solicitud_acceso:{solicitud_id}",
                detail=body.estado,
            )
        return actualizada, previa

    actualizada, previa = await run_db(_trabajo)
    if not actualizada:
        raise HTTPException(status_code=404, detail="solicitud no encontrada")

    if not avisar:
        return CambioEstadoOut(status="ok")

    if previa is None or previa.get("estado") == "atendida":
        # Ya estaba atendida (o desapareció entre la lectura y la escritura): el
        # estado queda bien, pero no se reenvía nada.
        return CambioEstadoOut(status="ok", notificado=False)

    # El correo va fuera del `run_db`: es I/O de red con su propio timeout, y
    # meterlo en el salto de base de datos retendría una conexión del pool
    # mientras habla un SMTP.
    email = str(previa.get("email") or "")
    empresa_valor = previa.get("empresa")
    empresa = str(empresa_valor) if empresa_valor else None
    notificado = await run_io(notificar_acceso_concedido, email=email, empresa=empresa)
    return CambioEstadoOut(status="ok", notificado=notificado)
