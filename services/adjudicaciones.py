"""Servicio de adjudicaciones — acceso de lectura para API y jobs.

Centraliza la lógica de carga de adjudicaciones, delegando en
``db/repositories/adjudicaciones.py`` para queries SQL. Las analíticas ya NO
pasan por aquí: agregan en Postgres o consumen proyecciones acotadas del
repositorio (ADR-023) — el loader full-table ``load_raw_adjudicaciones``, su
caché y el loader enriquecido sin consumidores se retiraron al migrar el
último endpoint, junto con el cortacircuitos de Render que los bloqueaba.
"""

from __future__ import annotations

from typing import Any

from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AdjudicacionRepository()


def load_for_competitors(
    *,
    ccaa: str | None = None,
    tecnologia: str | None = None,
    estado: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    importe_min: float | None = None,
) -> list[dict[str, Any]]:
    """Carga filtrada+proyectada para ``services/analytics/competitors.py``.

    Aplica los filtros en el ``WHERE`` SQL — sin caché: cada combinación de
    filtros es una query distinta y Postgres la resuelve en milisegundos.
    """
    return _repo.load_for_competitors(
        ccaa=ccaa,
        tecnologia=tecnologia,
        estado=estado,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        importe_min=importe_min,
    )


def load_licitadores(
    ccaa_filter: tuple[str, ...] | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Carga adjudicaciones con datos para el ranking de licitadores."""
    return _repo.load_licitadores(ccaa_filter=ccaa_filter, limit=limit)
