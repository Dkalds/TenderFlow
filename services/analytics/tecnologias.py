"""Tecnologias analytics — technology distribution, cross-tabs and detail.

Explota ``tecnologia`` (CSV) y agrega vía SQL (``db.repositories.aggregates``)
en vez de cargar la tabla ``licitaciones`` completa a pandas — la agregación
por CÓDIGO crudo se hace en Postgres (``unnest(string_to_array(...))`` +
``GROUP BY``); el mapeo código→label legible (``services/classification.
TECHNOLOGY_LABELS``, un dict Python) y el re-merge de códigos que comparten
label se hacen en Python sobre el resultado YA agregado (post-procesamiento
ligero).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.classification import TECHNOLOGY_LABELS, estado_label, tecnologia_label

log = get_logger(__name__)

_repo = AggregateRepository()

# Bounds to keep payloads small / charts readable.
_TOP_ORGANOS = 10
_TOP_CCAA = 10
_TOP_TECHS_CROSS = 10
_TOP_TECHS_EVOL = 8
_OTRAS = "Otras"
_OTRAS_SENTINEL = "__OTRAS__"


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TecnologiasFilters(BaseModel):
    """Query filters for the tecnologias endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None


class TecnologiaEntry(BaseModel):
    """Single technology aggregate (keyed by readable label)."""

    tecnologia: str
    count: int
    importe: float
    importe_medio: float
    pct: float
    pct_adjudicado: float


class CrossOrganoEntry(BaseModel):
    """tecnologia x organo cell."""

    organo: str
    tecnologia: str
    count: int


class CrossGeoEntry(BaseModel):
    """tecnologia x ccaa cell."""

    ccaa: str
    tecnologia: str
    count: int


class EvolucionEntry(BaseModel):
    """Monthly point for a technology."""

    mes: str
    tecnologia: str
    count: int
    importe: float


class TecnologiasResult(BaseModel):
    """Combined tecnologias response."""

    tecnologias: list[TecnologiaEntry] = Field(default_factory=list)
    sin_clasificar: int = 0
    # Total de licitaciones en alcance (denominador para la cobertura del
    # clasificador: % clasificado = (total - sin_clasificar) / total).
    total: int = 0
    # KPIs
    n_tecnologias: int = 0
    tecnologia_lider: str | None = None
    lider_count: int = 0
    importe_medio_global: float = 0.0
    tasa_adjudicacion_media: float = 0.0
    # Cross-tabs
    cross_organo: list[CrossOrganoEntry] = Field(default_factory=list)
    cross_geo: list[CrossGeoEntry] = Field(default_factory=list)
    evolucion_mensual: list[EvolucionEntry] = Field(default_factory=list)


class TecnologiaDetalleFilters(BaseModel):
    """Query filters for the per-technology detail endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    limit: int = 100


class TecnologiaDetalleItem(BaseModel):
    """Single tender row in the detail table."""

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    estado: str | None = None
    ccaa: str | None = None
    fecha_publicacion: str | None = None


class TecnologiaDetalleResult(BaseModel):
    """Detail payload for a single technology."""

    tecnologia: str
    n: int = 0
    importe_total: float = 0.0
    importe_medio: float = 0.0
    items: list[TecnologiaDetalleItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_repo_filters(filters: TecnologiasFilters | TecnologiaDetalleFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        ccaa=filters.ccaa,
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
    )


def _codes_for_label(tecnologia: str) -> list[str]:
    """Códigos crudos que mapean al label dado.

    ``tecnologia_label`` es un dict lookup con fallback identidad (un código
    no presente en ``TECHNOLOGY_LABELS`` es su propio label) — la relación es
    inyectiva (ningún label conocido se repite para dos códigos distintos),
    así que "códigos que producen este label" es, o bien las claves del dict
    cuyo valor coincide, o el propio ``tecnologia`` como código sin mapear.
    """
    codes = [code for code, label in TECHNOLOGY_LABELS.items() if label == tecnologia]
    if tecnologia not in codes:
        codes.append(tecnologia)
    return codes


def _merge_entries_by_label(
    raw_entries: list[dict[str, Any]], total: int
) -> list[TecnologiaEntry]:
    """Re-agrupa por label legible (varios códigos pueden compartir label)."""
    merged: dict[str, dict[str, float]] = {}
    for row in raw_entries:
        label = tecnologia_label(row["code"])
        acc = merged.setdefault(label, {"count": 0, "importe": 0.0, "adjudicadas": 0})
        acc["count"] += int(row["count"])
        acc["importe"] += float(row["importe"])
        acc["adjudicadas"] += int(row["adjudicadas"])

    entries = [
        TecnologiaEntry(
            tecnologia=label,
            count=int(data["count"]),
            importe=float(data["importe"]),
            importe_medio=(float(data["importe"]) / data["count"]) if data["count"] else 0.0,
            pct=round(data["count"] / total * 100, 2) if total else 0.0,
            pct_adjudicado=(
                round(data["adjudicadas"] / data["count"] * 100, 1) if data["count"] else 0.0
            ),
        )
        for label, data in merged.items()
    ]
    entries.sort(key=lambda e: e.count, reverse=True)
    return entries


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_tecnologias(filters: TecnologiasFilters) -> TecnologiasResult:
    """Compute technology distribution, KPIs and cross-dimensional breakdowns."""
    log.info("analytics_tecnologias_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)

    total, sin_clasificar = _repo.tecnologias_total_y_sin_clasificar(repo_filters)
    if total == 0:
        log.info("analytics_tecnologias_done", total=0)
        return TecnologiasResult()

    raw_entries = _repo.tecnologias_entries(repo_filters)
    if not raw_entries:
        return TecnologiasResult(sin_clasificar=sin_clasificar, total=total)

    entries = _merge_entries_by_label(raw_entries, total)

    n_tecnologias = len(entries)
    lider = max(entries, key=lambda e: e.count) if entries else None
    importe_medio_global = (
        float(sum(e.importe for e in entries) / n_tecnologias) if n_tecnologias else 0.0
    )
    tasa_adjudicacion_media = (
        float(sum(e.pct_adjudicado for e in entries) / n_tecnologias) if n_tecnologias else 0.0
    )

    raw_cross_organo = _repo.tecnologias_cross_organo(
        repo_filters, top_organos=_TOP_ORGANOS, top_techs=_TOP_TECHS_CROSS
    )
    cross_organo = [
        CrossOrganoEntry(
            organo=str(row["organo"]),
            tecnologia=tecnologia_label(row["code"]),
            count=int(row["count"]),
        )
        for row in raw_cross_organo
    ]

    raw_cross_geo = _repo.tecnologias_cross_geo(
        repo_filters, top_ccaa=_TOP_CCAA, top_techs=_TOP_TECHS_EVOL
    )
    cross_geo = [
        CrossGeoEntry(
            ccaa=str(row["ccaa"]), tecnologia=tecnologia_label(row["code"]), count=int(row["count"])
        )
        for row in raw_cross_geo
    ]

    raw_evolucion = _repo.tecnologias_evolucion(repo_filters, top_techs=_TOP_TECHS_EVOL)
    evolucion_mensual = [
        EvolucionEntry(
            mes=row["mes"],
            tecnologia=(
                _OTRAS if row["tech_grp"] == _OTRAS_SENTINEL else tecnologia_label(row["tech_grp"])
            ),
            count=int(row["count"]),
            importe=float(row["importe"]),
        )
        for row in raw_evolucion
    ]

    result = TecnologiasResult(
        tecnologias=entries,
        sin_clasificar=sin_clasificar,
        total=total,
        n_tecnologias=n_tecnologias,
        tecnologia_lider=lider.tecnologia if lider else None,
        lider_count=lider.count if lider else 0,
        importe_medio_global=round(importe_medio_global, 2),
        tasa_adjudicacion_media=round(tasa_adjudicacion_media, 1),
        cross_organo=cross_organo,
        cross_geo=cross_geo,
        evolucion_mensual=evolucion_mensual,
    )
    log.info(
        "analytics_tecnologias_done",
        total=n_tecnologias,
        sin_clasificar=sin_clasificar,
    )
    return result


def get_tecnologia_detalle(
    tecnologia: str, filters: TecnologiaDetalleFilters
) -> TecnologiaDetalleResult:
    """Top-N tenders for a single technology label, plus subset KPIs."""
    log.info("analytics_tecnologia_detalle_start", tecnologia=tecnologia)
    repo_filters = _to_repo_filters(filters)
    tech_codes = _codes_for_label(tecnologia)

    n, importe_total, importe_medio = _repo.tecnologia_detalle_kpis(
        repo_filters, tech_codes=tech_codes
    )
    if n == 0:
        return TecnologiaDetalleResult(tecnologia=tecnologia)

    raw_items = _repo.tecnologia_detalle_items(
        repo_filters, tech_codes=tech_codes, limit=filters.limit
    )
    items = [
        TecnologiaDetalleItem(
            id_externo=str(row["id_externo"] or ""),
            titulo=row["titulo"],
            organo_contratacion=row["organo_contratacion"],
            importe=float(row["importe"]) if row["importe"] is not None else None,
            estado=estado_label(row["estado"]) if row["estado"] else None,
            ccaa=row["ccaa"],
            fecha_publicacion=(row["fecha_publicacion"] or "")[:10] or None,
        )
        for row in raw_items
    ]

    log.info("analytics_tecnologia_detalle_done", tecnologia=tecnologia, n=n)
    return TecnologiaDetalleResult(
        tecnologia=tecnologia,
        n=n,
        importe_total=importe_total,
        importe_medio=importe_medio,
        items=items,
    )
