"""Rutas de resoluciones de recursos contractuales (Fase 5.3).

- ``GET /resoluciones`` — feed de jurisprudencia filtrable por órgano,
  sentido y fecha; con ``licitacion_id`` alimenta el bloque "Recursos" del
  detail panel del frontend.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from services.resoluciones import SENTIDOS_VALIDOS, resoluciones

router = APIRouter(tags=["resoluciones"])


class ResolucionOut(BaseModel):
    """Resolución de recurso contractual, con la licitación vinculada si la hay."""

    id: int
    tribunal: str | None
    numero_resolucion: str | None
    numero_recurso: str | None
    fecha: str | None
    expediente: str | None
    organo: str | None
    sentido: str | None
    url_pdf: str | None
    resumen: str | None
    licitacion_id: str | None
    licitacion_titulo: str | None


class ResolucionesResult(BaseModel):
    items: list[ResolucionOut]


@router.get("/resoluciones", summary="Resoluciones de recursos contractuales (TACRC)")
async def get_resoluciones(
    organo: str | None = Query(None, description="Filtro por órgano (substring)"),
    sentido: str | None = Query(
        None, description="Filtro: estimado|desestimado|inadmitido|desistimiento"
    ),
    desde: str | None = Query(None, description="Fecha mínima YYYY-MM-DD"),
    licitacion_id: str | None = Query(
        None, description="Solo resoluciones vinculadas a esta licitación"
    ),
    limit: int = Query(100, ge=1, le=500),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> ResolucionesResult:
    if sentido and sentido not in SENTIDOS_VALIDOS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Sentido inválido. Válidos: {sorted(SENTIDOS_VALIDOS)}",
        )
    items = await run_db(
        resoluciones,
        organo=organo,
        sentido=sentido,
        desde=desde,
        licitacion_id=licitacion_id,
        limit=limit,
    )
    return ResolucionesResult(items=[ResolucionOut(**item) for item in items])
