"""Geography analytics — distribution by CCAA.

Agrega en Postgres vía :class:`AggregateRepository` (ADR-023); hasta 2026-08
cargaba la tabla completa a pandas en el proceso API — bloqueado en Render por
el cortacircuitos full-table, que dejaba este endpoint vacío en producción.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AggregateRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class GeoFilters(BaseModel):
    """Query filters for geography."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    tecnologia: str | None = None


class GeoEntry(BaseModel):
    """Single CCAA entry."""

    ccaa: str
    count: int
    importe: float
    pct: float


class ProvinciaEntry(BaseModel):
    """Single provincia entry (aggregated over the full filtered dataset)."""

    provincia: str
    count: int
    importe: float


class GeoResult(BaseModel):
    """Combined geography response."""

    by_ccaa: list[GeoEntry] = Field(default_factory=list)
    by_provincia: list[ProvinciaEntry] = Field(default_factory=list)
    concentracion_top3: float = 0.0
    ccaa_mas_activa: str | None = None


def _to_repo_filters(filters: GeoFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        tecnologia=filters.tecnologia,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_geography(filters: GeoFilters) -> GeoResult:
    """Compute geographic distribution by CCAA (GROUP BY en Postgres)."""
    log.info("analytics_geography_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)

    ccaa_rows = _repo.geography_by_ccaa(repo_filters)
    if not ccaa_rows:
        log.info("analytics_geography_done", entries=0)
        return GeoResult()

    total = sum(int(r["count"]) for r in ccaa_rows)
    entries = [
        GeoEntry(
            ccaa=str(r["ccaa"]),
            count=int(r["count"]),
            importe=float(r["importe"] or 0),
            pct=float(int(r["count"]) / total * 100) if total else 0.0,
        )
        for r in ccaa_rows
    ]

    top3_pct = sum(e.pct for e in entries[:3])
    most_active = entries[0].ccaa if entries else None

    # Agregación por provincia sobre TODO el dataset filtrado (antes el frontend
    # sumaba un sample de `licitaciones?limit=500` que ignoraba los filtros).
    by_provincia = [
        ProvinciaEntry(
            provincia=str(r["provincia"]),
            count=int(r["count"]),
            importe=float(r["importe"] or 0),
        )
        for r in _repo.geography_by_provincia(repo_filters)
    ]

    result = GeoResult(
        by_ccaa=entries,
        by_provincia=by_provincia,
        concentracion_top3=top3_pct,
        ccaa_mas_activa=most_active,
    )
    log.info("analytics_geography_done", entries=len(entries))
    return result
