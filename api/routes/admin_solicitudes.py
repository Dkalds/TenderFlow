"""Admin endpoints — cola de solicitudes de acceso llegadas desde la landing.

Requiere autenticación dual (sesión o API key) + is_admin, como el resto de
``/admin``. Aprobar una solicitud **no** se hace desde aquí: la allowlist de
acceso vive en ``OAUTH_ALLOWED_EMAILS``/``OAUTH_ALLOWED_DOMAINS`` y sigue
siendo una decisión de operación. Lo que da esta cola es saber que la petición
existe y poder marcarla como atendida o descartada.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.dual_auth import require_admin
from db.audit import log_event
from db.solicitudes_acceso import ESTADOS, actualizar_estado, listar_solicitudes
from observability.logging import get_logger
from shared.dto import StatusOk

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


@router.patch("/{solicitud_id}", response_model=StatusOk)
async def cambiar_estado(
    solicitud_id: int,
    body: EstadoBody,
    admin: dict[str, Any] = Depends(require_admin),
) -> StatusOk:
    if body.estado not in ESTADOS:
        raise HTTPException(status_code=422, detail=f"estado no válido: {body.estado}")

    def _trabajo() -> bool:
        # El cambio de estado y su registro de auditoría son dos escrituras
        # síncronas: van juntas en un único salto al threadpool. Dejar el
        # `log_event` fuera bloqueaba el event loop —y con él, todos los demás
        # endpoints del proceso— mientras escribía.
        actualizada = actualizar_estado(solicitud_id, body.estado)
        if actualizada:
            log_event(
                event_type="solicitud_acceso.estado",
                user_key=str(admin.get("user_id", "")),
                resource=f"solicitud_acceso:{solicitud_id}",
                detail=body.estado,
            )
        return actualizada

    if not await run_db(_trabajo):
        raise HTTPException(status_code=404, detail="solicitud no encontrada")
    return StatusOk(status="ok")
