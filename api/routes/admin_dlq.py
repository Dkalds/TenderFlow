"""Admin — Dead Letter Queue de la ingesta (RFC ux-calidad-datos #4).

La tarjeta «Gestión de DLQ» de la consola enseñaba un número y un botón que
respondía «Funcionalidad en desarrollo». Aquí está lo que le faltaba:

- ``GET /admin/dlq``: las entradas (abiertas o agotadas) y el resumen por
  fuente, para saber QUÉ falló antes de tocar nada.
- ``POST /admin/dlq/{id}/reintentar``: devuelve una entrada a la cola.

Reintentar **no** ejecuta el conector en la petición: eso son minutos (u horas
para un mes bulk) y no cabe en un request HTTP. Deja la entrada vencida para
el próximo ciclo de ``scheduler.dlq_retry``, que es quien sabe despachar cada
fuente (ver :func:`db.dlq.requeue`).

Sólo administradores de la plataforma: la DLQ es de la ingesta, que es común a
todas las organizaciones, así que no hay «owner» de organización que pueda
decidir sobre ella. Cada reencolado queda en ``audit_log`` (``dlq.requeued``).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from api.concurrency import run_db
from api.routes.dual_auth import require_admin
from db.audit import log_event
from db.dlq import list_exhausted, list_unresolved, requeue, unresolved_summary
from observability.logging import get_logger
from shared.audit_events import DLQ_REQUEUED

log = get_logger(__name__)

router = APIRouter(prefix="/admin/dlq", tags=["admin"])


class DlqEntrada(BaseModel):
    """Una extracción fallida."""

    id: int
    fuente: str
    scope: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    created_at: str | None = None
    last_attempt_at: str | None = None
    exhausted_at: str | None = None


class DlqResumenFuente(BaseModel):
    """Fallos abiertos agrupados por fuente/scope."""

    fuente: str
    scope: str = ""
    n: int
    retries: int = 0
    first_seen: str | None = None
    last_attempt: str | None = None


class DlqListado(BaseModel):
    estado: Literal["abiertas", "agotadas"]
    items: list[DlqEntrada] = Field(default_factory=list)
    resumen: list[DlqResumenFuente] = Field(
        default_factory=list,
        description="Abiertas por fuente/scope (siempre, sea cual sea `estado`).",
    )


class DlqReintento(BaseModel):
    """Resultado de reencolar una entrada."""

    id: int
    estado_previo: Literal["abierta", "agotada", "duplicada", "resuelta"]
    reencolada: bool
    detalle: str


def _txt(valor: Any) -> str | None:
    return None if valor is None else str(valor)


def _entrada(fila: dict[str, Any]) -> DlqEntrada:
    return DlqEntrada(
        id=int(fila["id"]),
        fuente=str(fila.get("fuente") or ""),
        scope=_txt(fila.get("scope")),
        error_type=_txt(fila.get("error_type")),
        error_message=_txt(fila.get("error_message")),
        retry_count=int(fila.get("retry_count") or 0),
        created_at=_txt(fila.get("created_at")),
        last_attempt_at=_txt(fila.get("last_attempt_at")),
        exhausted_at=_txt(fila.get("exhausted_at")),
    )


@router.get("", response_model=DlqListado, summary="Entradas de la DLQ de ingesta")
async def listar_dlq(
    estado: Literal["abiertas", "agotadas"] = Query(
        "abiertas", description="Abiertas (en ciclo de reintento) o agotadas (sin más intentos)"
    ),
    limit: int = Query(50, ge=1, le=200),
    _admin: dict[str, Any] = Depends(require_admin),
) -> DlqListado:
    def _trabajo() -> DlqListado:
        filas = list_exhausted(limit) if estado == "agotadas" else list_unresolved(limit)
        return DlqListado(
            estado=estado,
            items=[_entrada(f) for f in filas],
            resumen=[
                DlqResumenFuente(
                    fuente=str(r.get("fuente") or ""),
                    scope=str(r.get("scope") or ""),
                    n=int(r.get("n") or 0),
                    retries=int(r.get("retries") or 0),
                    first_seen=_txt(r.get("first_seen")),
                    last_attempt=_txt(r.get("last_attempt")),
                )
                for r in unresolved_summary()
            ],
        )

    return await run_db(_trabajo)


_DETALLES = {
    "abierta": "Reencolada: se reintentará en el próximo ciclo de reintentos de la ingesta.",
    "agotada": "Reabierta con el contador a cero: vuelve al ciclo de reintentos de la ingesta.",
    "duplicada": (
        "No se reabre: ya hay otra entrada abierta para la misma fuente y ámbito, "
        "que es la que se reintentará."
    ),
    "resuelta": "Ya estaba resuelta: no hay nada que reintentar.",
}


@router.post(
    "/{failure_id}/reintentar",
    response_model=DlqReintento,
    summary="Devolver una entrada de la DLQ a la cola de reintentos",
    responses={404: {"description": "La entrada no existe"}},
)
async def reintentar_dlq(
    failure_id: int = Path(ge=1),
    admin: dict[str, Any] = Depends(require_admin),
) -> DlqReintento:
    previo = await run_db(requeue, failure_id)
    if previo == "inexistente":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Entrada DLQ {failure_id} no encontrada.",
        )
    reencolada = previo in ("abierta", "agotada")
    if reencolada:
        await run_db(
            log_event,
            event_type=DLQ_REQUEUED,
            actor=str(admin.get("user_id", "")),
            user_id=int(admin["user_id"]) if admin.get("user_id") is not None else None,
            resource=f"failed_extraction:{failure_id}",
            detail=f"estado_previo={previo}",
        )
        log.info("dlq_requeued", failure_id=failure_id, estado_previo=previo)
    return DlqReintento(
        id=failure_id,
        estado_previo=previo,
        reencolada=reencolada,
        detalle=_DETALLES[previo],
    )
