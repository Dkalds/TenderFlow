"""Ruta /api/v1/meta — metadatos para filtros de búsqueda.

GET /api/v1/meta/filters — devuelve listas válidas de estado, ccaa, tecnologia, cpv.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from api.cache import cache_get, cache_key, cache_set
from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.repositories.licitaciones import LicitacionRepository
from shared.cache import single_flight

router = APIRouter(prefix="/meta", tags=["meta"])

_lic_repo = LicitacionRepository()
_FILTERS_CACHE_KEY = cache_key("meta", "filters")
_FILTERS_TTL = 300  # 5 minutos
_LAST_EXTRACTION_CACHE_KEY = cache_key("meta", "last-extraction")
# Un minuto: el dato solo cambia cuando termina una ingesta, y el frontend lo
# pide en cada carga de página. Ver el docstring del endpoint.
_LAST_EXTRACTION_TTL = 60


class MetaFilters(BaseModel):
    """Valores únicos disponibles para los selectores de filtros."""

    estado: list[str]
    ccaa: list[str]
    tecnologia: list[str]
    cpv: list[str]


class LastExtraction(BaseModel):
    last_extraction: str | None


@router.get(
    "/filters",
    summary="Valores válidos para los filtros de búsqueda",
    responses={401: {"description": "API key inválida"}},
)
async def get_filter_options(
    response: Response,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> MetaFilters:
    """Devuelve los valores únicos disponibles para cada filtro de licitaciones.

    Útil para construir selectores y validar parámetros en el cliente.
    Respuesta cacheada 5 minutos (``X-Cache: HIT`` si viene del cache).

    Response::

        {
            "estado": ["ADJ", "EV", "PUB", ...],
            "ccaa": ["Andalucía", "Cataluña", ...],
            "tecnologia": ["SAP", "ORACLE", "MICROSOFT", ...],
            "cpv": ["72000000", ...]
        }
    """
    cached = cache_get(_FILTERS_CACHE_KEY)
    if cached is not None:
        response.headers["X-Cache"] = "HIT"
        return MetaFilters(**cast("dict[str, Any]", cached))

    # El TTL por sí solo no evita la estampida: las peticiones que llegan con el
    # caché frío fallan todas la comprobación de arriba y todas ejecutan la
    # consulta. Dentro del lock hay que volver a leer, porque quien esperaba lo
    # hacía mientras otra corrutina rellenaba la entrada.
    async with single_flight(_FILTERS_CACHE_KEY):
        cached = cache_get(_FILTERS_CACHE_KEY)
        if cached is not None:
            response.headers["X-Cache"] = "HIT"
            return MetaFilters(**cast("dict[str, Any]", cached))

        result = await run_db(_lic_repo.get_filter_options)
        cache_set(_FILTERS_CACHE_KEY, result, ttl=_FILTERS_TTL)

    response.headers["X-Cache"] = "MISS"
    return MetaFilters(**result)


@router.get(
    "/last-extraction",
    summary="Fecha de la última extracción de datos",
    responses={401: {"description": "API key inválida"}},
)
async def get_last_extraction(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> LastExtraction:
    """Devuelve la fecha/hora de la última extracción del scraper.

    Cacheado 60 s: el valor solo cambia al terminar una ingesta, pero el
    frontend lo pide en cada carga de página. Era la tercera consulta más cara
    de producción (134 llamadas, 16,6 s de media, 93 s de pico) porque
    ``MAX(fecha_extraccion)`` no tenía índice; v77 lo añade y esto evita además
    que varias pestañas repitan la consulta mientras el caché está frío.

    Se cachea un ``dict`` y no el ``str`` pelado para que ``None`` (corpus
    vacío) sea un valor cacheable y no se confunda con "no hay entrada".
    """
    cached = cache_get(_LAST_EXTRACTION_CACHE_KEY)
    if cached is None:
        async with single_flight(_LAST_EXTRACTION_CACHE_KEY):
            cached = cache_get(_LAST_EXTRACTION_CACHE_KEY)
            if cached is None:
                date = await run_db(_lic_repo.get_last_extraction_date)
                cached = {"last_extraction": date}
                cache_set(_LAST_EXTRACTION_CACHE_KEY, cached, ttl=_LAST_EXTRACTION_TTL)
    return LastExtraction(**cast("dict[str, Any]", cached))
