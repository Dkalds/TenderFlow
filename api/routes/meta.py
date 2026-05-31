"""Ruta /api/v1/meta — metadatos para filtros de búsqueda.

GET /api/v1/meta/filters — devuelve listas válidas de estado, ccaa, tecnologia, cpv.
"""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Depends, Response

from api.cache import cache_get, cache_key, cache_set
from api.concurrency import run_db
from api.routes.dual_auth import require_any_auth
from db.repositories.licitaciones import LicitacionRepository

router = APIRouter(prefix="/meta", tags=["meta"])

_lic_repo = LicitacionRepository()
_FILTERS_CACHE_KEY = cache_key("meta", "filters")
_FILTERS_TTL = 300  # 5 minutos


@router.get(
    "/filters",
    summary="Valores válidos para los filtros de búsqueda",
    responses={401: {"description": "API key inválida"}},
)
async def get_filter_options(
    response: Response,
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, Any]:
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
        return cast(dict[str, Any], cached)

    result = await run_db(_lic_repo.get_filter_options)
    cache_set(_FILTERS_CACHE_KEY, result, ttl=_FILTERS_TTL)
    response.headers["X-Cache"] = "MISS"
    return result


@router.get(
    "/last-extraction",
    summary="Fecha de la última extracción de datos",
    responses={401: {"description": "API key inválida"}},
)
async def get_last_extraction(
    _ctx: dict[str, Any] = Depends(require_any_auth),
) -> dict[str, str | None]:
    """Devuelve la fecha/hora de la última extracción del scraper."""
    date = await run_db(_lic_repo.get_last_extraction_date)
    return {"last_extraction": date}
