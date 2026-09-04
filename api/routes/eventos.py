"""Rutas de eventos de contrato (Fase 4).

- ``GET /licitaciones/{id}/eventos`` — línea de tiempo completa de un
  contrato: publicación, adjudicaciones (con empresa canónica),
  formalizaciones, modificaciones de importe, prórrogas y anulaciones.
- ``GET /eventos`` — feed reciente filtrable por tipo, para el dashboard.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.repositories.aggregates import LicitacionesFilters
from db.repositories.licitaciones import LicitacionRepository
from services.contract_events import EventoFeedItem, EventosFeedResult, eventos_recientes, timeline

router = APIRouter(tags=["eventos"])

_TIPOS_VALIDOS = {
    "adjudicacion",
    "formalizacion",
    "modificacion",
    "prorroga",
    "anulacion",
    "cambio_estado",
    "recurso",
}


_repo_licitaciones = LicitacionRepository()


class TimelineEvento(BaseModel):
    """Hito de la línea de tiempo (evento materializado o implícito)."""

    fecha: str | None
    tipo: str
    campo: str | None
    valor_antes: str | None
    valor_despues: str | None
    importe_delta: float | None
    detalle: str | None


class TimelineResult(BaseModel):
    licitacion_id: str
    items: list[TimelineEvento]


@router.get(
    "/licitaciones/{licitacion_id:path}/eventos",
    summary="Línea de tiempo de un contrato",
    responses={404: {"description": "Licitación no encontrada"}},
)
async def get_timeline(
    licitacion_id: str,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> TimelineResult:
    """Hitos del ciclo de vida: publicación → adjudicación → formalización →
    modificaciones/prórrogas → anulación, ordenados cronológicamente."""
    if not await run_db(_repo_licitaciones.exists, licitacion_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Licitación no encontrada."
        )
    items = await run_db(timeline, licitacion_id)
    return TimelineResult(
        licitacion_id=licitacion_id, items=[TimelineEvento(**item) for item in items]
    )


@router.get(
    "/eventos",
    summary="Feed de eventos de contrato recientes",
    response_model=EventosFeedResult,
)
async def get_eventos(
    tipo: str | None = Query(
        None, description="Filtro: adjudicacion|formalizacion|modificacion|prorroga|anulacion"
    ),
    dias: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500),
    fecha_desde: date | None = Query(
        None, description="Movimientos desde esta fecha (sustituye a `dias`)"
    ),
    fecha_hasta: date | None = Query(None, description="Movimientos hasta esta fecha"),
    ccaa: str | None = Query(None, description="Comunidad Autónoma de la licitación"),
    tecnologia: str | None = Query(None, description="Tecnología de la licitación"),
    estado: str | None = Query(None, description="Estado de la licitación (PUB, EV, ADJ…)"),
    importe_min: float | None = Query(None, ge=0, description="Importe mínimo (EUR)"),
    solo_abiertas: bool = Query(
        False, description="Solo licitaciones que siguen abiertas (no terminales)"
    ),
    q: str | None = Query(
        None, max_length=200, description="Búsqueda en título, órgano o expediente"
    ),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> EventosFeedResult:
    """Movimientos de contrato recientes, acotados por el ámbito global.

    Los filtros de licitación (CCAA, tecnología, estado, importe, búsqueda) se
    aplican sobre el expediente movido, así que el feed mide el mismo universo
    que el resto del Resumen. Las fechas acotan **el movimiento**, no la
    publicación del expediente: la pregunta del feed es qué ha cambiado en la
    ventana, y una ventana sobre `fecha_publicacion` dejaría el panel vacío en
    cuanto el ámbito mirase a meses anteriores.
    """
    tipos: tuple[str, ...] | None = None
    if tipo:
        if tipo not in _TIPOS_VALIDOS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Tipo inválido. Válidos: {sorted(_TIPOS_VALIDOS)}",
            )
        tipos = (tipo,)
    filters = LicitacionesFilters(
        ccaa=ccaa,
        tecnologia=tecnologia,
        estado=estado,
        importe_min=importe_min,
        solo_abiertas=solo_abiertas,
        q=q,
    )
    items = await run_db(
        eventos_recientes,
        tipos=tipos,
        dias=dias,
        limit=limit,
        desde=fecha_desde.isoformat() if fecha_desde else None,
        hasta=fecha_hasta.isoformat() if fecha_hasta else None,
        filters=filters,
    )
    return EventosFeedResult(items=[EventoFeedItem(**i) for i in items], dias=dias)
