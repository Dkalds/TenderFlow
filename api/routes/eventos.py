"""Rutas de eventos de contrato (Fase 4).

- ``GET /licitaciones/{id}/eventos`` — línea de tiempo completa de un
  contrato: publicación, adjudicaciones (con empresa canónica),
  formalizaciones, modificaciones de importe, prórrogas y anulaciones.
- ``GET /eventos`` — feed reciente filtrable por tipo, para el dashboard.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.database import connect_read
from services.contract_events import eventos_recientes, timeline

router = APIRouter(tags=["eventos"])

_TIPOS_VALIDOS = {
    "adjudicacion",
    "formalizacion",
    "modificacion",
    "prorroga",
    "anulacion",
    "cambio_estado",
}


def _licitacion_existe(licitacion_id: str) -> bool:
    with connect_read() as c:
        return (
            c.execute(
                "SELECT 1 FROM licitaciones WHERE id_externo = ?", (licitacion_id,)
            ).fetchone()
            is not None
        )


@router.get(
    "/licitaciones/{licitacion_id}/eventos",
    summary="Línea de tiempo de un contrato",
    responses={404: {"description": "Licitación no encontrada"}},
)
async def get_timeline(
    licitacion_id: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
    """Hitos del ciclo de vida: publicación → adjudicación → formalización →
    modificaciones/prórrogas → anulación, ordenados cronológicamente."""
    if not await run_db(_licitacion_existe, licitacion_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada."
        )
    items = await run_db(timeline, licitacion_id)
    return {"licitacion_id": licitacion_id, "items": items}


@router.get("/eventos", summary="Feed de eventos de contrato recientes")
async def get_eventos(
    tipo: str | None = Query(
        None, description="Filtro: adjudicacion|formalizacion|modificacion|prorroga|anulacion"
    ),
    dias: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
    tipos: tuple[str, ...] | None = None
    if tipo:
        if tipo not in _TIPOS_VALIDOS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Tipo inválido. Válidos: {sorted(_TIPOS_VALIDOS)}",
            )
        tipos = (tipo,)
    items = await run_db(eventos_recientes, tipos=tipos, dias=dias, limit=limit)
    return {"items": items, "dias": dias}
