"""Familia **adjudicaciones**: ``/adjudicaciones``, que no cuelga de un expediente.

Vive en este paquete porque comparte repositorio y modelos con las licitaciones
—una adjudicación es el desenlace de una—, pero es su propio recurso de primer
nivel y por eso tiene su propio módulo en vez de esconderse en el listado.
"""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from pydantic import BaseModel

from api.concurrency import run_db
from api.pagination import PageParams, pagina
from api.routes.dual_auth import require_any_auth
from api.routes.licitaciones._base import (
    _adj_repo,
    _validate_date,
)
from observability.logging import get_logger
from shared.dto import (
    PaginatedResponse,
)

log = get_logger(__name__)

router = APIRouter(tags=["licitaciones"])


# ── /adjudicaciones ───────────────────────────────────────────────────────


class AdjudicacionSummary(BaseModel):
    id: int
    licitacion_id: str
    nombre: str
    nif: str | None = None
    importe_adjudicado: float | None = None
    fecha_adjudicacion: str | None = None
    ccaa: str | None = None
    es_pyme: int | None = None
    n_ofertas_recibidas: int | None = None


@router.get(
    "/adjudicaciones",
    response_model=PaginatedResponse[AdjudicacionSummary],
    summary="Listado paginado de adjudicaciones",
    responses={
        401: {"description": "API key inválida"},
        422: {"description": "Parámetros inválidos"},
    },
)
async def list_adjudicaciones(
    licitacion_id: str | None = Query(None, description="Filtrar por ID de licitación"),
    ccaa: str | None = Query(None, description="Comunidad Autónoma de la empresa"),
    fecha_desde: str | None = Query(None, description="Fecha adjudicación desde"),
    fecha_hasta: str | None = Query(None, description="Fecha adjudicación hasta"),
    with_total: bool = Query(True, description="Incluir total"),
    page: PageParams = Depends(pagina(50)),
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> PaginatedResponse[AdjudicacionSummary]:
    """Devuelve lista paginada de adjudicaciones."""
    _validate_date(fecha_desde, "fecha_desde")
    _validate_date(fecha_hasta, "fecha_hasta")

    items, total = await run_db(
        _adj_repo.list_paginated,
        licitacion_id=licitacion_id,
        ccaa=ccaa,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        limit=page.limit,
        offset=page.offset,
        with_total=with_total,
    )

    return PaginatedResponse[AdjudicacionSummary](
        total=total,
        limit=page.limit,
        offset=page.offset,
        items=[AdjudicacionSummary.model_validate(d) for d in items],
    )
