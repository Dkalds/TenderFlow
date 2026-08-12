"""Resumen analytics — novedades, hoy, timeline, sankey, top licitaciones.

Los cinco endpoints agregan en Postgres vía ``db.repositories.aggregates``
(ADR-023). Antes materializaban la tabla ``licitaciones`` completa en pandas
(``load_stats_base_df``, ya retirado), que en el proceso web de Render
devolvía un DataFrame vacío por el cortacircuitos full-table (también
retirado al completar la migración): respondían 200 con el payload a cero y
la pantalla salía en blanco, sin error que lo delatara.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from db.repositories.kpi_snapshots import read_overview_snapshot_for
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AggregateRepository()

# Cota de puntos del scatter de /resumen/timeline (la misma que aplicaba el
# ``head(1000)`` de pandas, ahora empujada al ``LIMIT`` de la query).
_TIMELINE_LIMIT = 1000
_NOVEDADES_SAMPLE = 10


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ResumenNovedadesSample(BaseModel):
    id_externo: str
    titulo: str | None = None
    importe: float | None = None
    organo_contratacion: str | None = None


class ResumenNovedadesResult(BaseModel):
    count: int = 0
    sample: list[ResumenNovedadesSample] = Field(default_factory=list)


class ResumenHoyFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class ResumenHoyResult(BaseModel):
    calientes: int = 0
    vencen_48h: int = 0
    nuevas_24h: int = 0
    total_activas: int = 0


class TimelineScatterFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class TimelineScatterItem(BaseModel):
    id_externo: str
    titulo: str | None = None
    importe: float | None = None
    fecha_publicacion: str | None = None
    estado: str | None = None
    organo_contratacion: str | None = None
    tipo_contrato: str | None = None
    ccaa: str | None = None


class TimelineScatterResult(BaseModel):
    items: list[TimelineScatterItem] = Field(default_factory=list)


class SankeyNode(BaseModel):
    id: str
    label: str


class SankeyLink(BaseModel):
    source: str
    target: str
    value: int


class SankeyFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class SankeyResult(BaseModel):
    nodes: list[SankeyNode] = Field(default_factory=list)
    links: list[SankeyLink] = Field(default_factory=list)


class TopLicitacionesFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    n: int = 10


class TopLicitacionItem(BaseModel):
    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    estado: str | None = None
    adjudicatario: str | None = None
    baja_pct: float | None = None


class TopLicitacionesResult(BaseModel):
    items: list[TopLicitacionItem] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_repo_filters(filters: Any) -> LicitacionesFilters:
    """Traduce los filtros del endpoint (fecha_desde/hasta, ccaa, tecnologia).

    Los tres DTOs de filtros de este módulo comparten esos cuatro campos; el
    resto de campos de :class:`LicitacionesFilters` no los expone ningún
    endpoint de resumen.
    """
    fecha_desde = getattr(filters, "fecha_desde", None)
    fecha_hasta = getattr(filters, "fecha_hasta", None)
    return LicitacionesFilters(
        ccaa=getattr(filters, "ccaa", None),
        tecnologia=getattr(filters, "tecnologia", None),
        fecha_desde=fecha_desde.isoformat() if fecha_desde else None,
        fecha_hasta=fecha_hasta.isoformat() if fecha_hasta else None,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_resumen_novedades(user_id: int) -> ResumenNovedadesResult:
    """New licitaciones since user's last login."""
    log.info("analytics_resumen_novedades_start", user_id=user_id)

    from db.users import get_user_by_id

    user = get_user_by_id(user_id)
    if not user:
        return ResumenNovedadesResult()

    last_login = user.get("last_login")
    if not last_login:
        return ResumenNovedadesResult()

    # ``last_login`` llega como string ISO o datetime según el driver; se
    # normaliza con la misma tolerancia que antes (valor ilegible -> sin
    # novedades, nunca una excepción) al formato ISO que espera el repository.
    ts = pd.to_datetime(last_login, errors="coerce", utc=True)
    if pd.isna(ts):
        return ResumenNovedadesResult()

    count, rows = _repo.resumen_novedades(desde_iso=ts.isoformat(), sample_limit=_NOVEDADES_SAMPLE)
    sample = [
        ResumenNovedadesSample(
            id_externo=str(row["id_externo"]),
            titulo=row.get("titulo"),
            importe=float(row["importe"]) if row.get("importe") is not None else None,
            organo_contratacion=row.get("organo_contratacion"),
        )
        for row in rows
    ]

    log.info("analytics_resumen_novedades_done", count=count)
    return ResumenNovedadesResult(count=count, sample=sample)


def get_resumen_hoy(filters: ResumenHoyFilters) -> ResumenHoyResult:
    """Para hoy — calientes, vencen 48h, nuevas 24h, total activas."""
    log.info("analytics_resumen_hoy_start", filters=filters.model_dump(exclude_none=True))

    hoy = datetime.now(UTC)
    repo_filters = _to_repo_filters(filters)
    # Mismo camino rápido que `/analytics/overview`: el P75 de importe y el
    # recuento de activas son globales y los deja precalculados el pipeline de
    # ingesta, así que sin filtros esta consulta deja de recorrer la tabla
    # entera. Sin snapshot (o con filtros) se calcula en vivo como antes.
    snap = read_overview_snapshot_for(repo_filters)
    counts = _repo.overview_para_hoy(
        repo_filters,
        hoy_iso=hoy.isoformat(),
        limite_48h_iso=(hoy + timedelta(hours=48)).isoformat(),
        hace_24h_iso=(hoy - timedelta(hours=24)).isoformat(),
        p75=snap.importe_p75 if snap is not None else None,
        total_activas=snap.total_activas if snap is not None else None,
    )

    result = ResumenHoyResult(
        calientes=counts["calientes_hoy"],
        vencen_48h=counts["vencen_48h"],
        nuevas_24h=counts["nuevas_24h"],
        total_activas=counts["total_activas"],
    )
    log.info("analytics_resumen_hoy_done")
    return result


def get_timeline_scatter(filters: TimelineScatterFilters) -> TimelineScatterResult:
    """Scatter data for all licitaciones (max 1000)."""
    log.info("analytics_timeline_scatter_start")

    rows = _repo.resumen_timeline_items(_to_repo_filters(filters), limit=_TIMELINE_LIMIT)
    items = [
        TimelineScatterItem(
            id_externo=str(row["id_externo"]),
            titulo=row.get("titulo"),
            importe=float(row["importe"]) if row.get("importe") is not None else None,
            fecha_publicacion=row.get("fecha_publicacion"),
            estado=row.get("estado"),
            organo_contratacion=row.get("organo_contratacion"),
            tipo_contrato=row.get("tipo_contrato"),
            ccaa=row.get("ccaa"),
        )
        for row in rows
    ]

    log.info("analytics_timeline_scatter_done", count=len(items))
    return TimelineScatterResult(items=items)


def get_sankey_flow(filters: SankeyFilters) -> SankeyResult:
    """Sankey: tipo_contrato → estado transitions (GROUP BY en Postgres)."""
    log.info("analytics_sankey_start")
    counts = _repo.resumen_sankey(_to_repo_filters(filters))
    if not counts:
        return SankeyResult()

    tipos = sorted({str(r["tipo_contrato"]) for r in counts})
    estados = sorted({str(r["estado"]) for r in counts})
    nodes: list[SankeyNode] = [SankeyNode(id=f"tipo_{t}", label=t) for t in tipos]
    nodes.extend(SankeyNode(id=f"estado_{e}", label=e) for e in estados)

    links = [
        SankeyLink(
            source=f"tipo_{r['tipo_contrato']}",
            target=f"estado_{r['estado']}",
            value=int(r["value"]),
        )
        for r in counts
    ]

    log.info("analytics_sankey_done", nodes=len(nodes), links=len(links))
    return SankeyResult(nodes=nodes, links=links)


def get_top_licitaciones(filters: TopLicitacionesFilters) -> TopLicitacionesResult:
    """Top N licitaciones by importe (ORDER BY … LIMIT en Postgres).

    La baja replica la fórmula del pandas original, que comparaba la suma de
    ``importe_adjudicado`` del grupo contra la suma de la columna
    ``importe_licitacion`` del join (``n_adj * importe`` de la licitación).
    """
    log.info("analytics_top_licitaciones_start", n=filters.n)
    rows = _repo.resumen_top_licitaciones(_to_repo_filters(filters), n=filters.n)

    items = []
    for r in rows:
        baja: float | None = None
        n_adj = int(r.get("n_adj") or 0)
        importe = r.get("importe")
        if n_adj > 0 and importe:
            # Baja agregada del expediente: todo lo adjudicado (suma de sus lotes)
            # contra el presupuesto ÚNICO del expediente. El denominador era
            # ``n_adj * importe`` — replicaba el bug del pandas original que sumaba
            # ``importe_licitacion`` del join (una copia de ``l.importe`` por fila),
            # inflando el divisor n veces: con 4 lotes adjudicados al completo daba
            # ~75% de baja en vez de ~0%. Para n_adj=1 el valor no cambia.
            imp_lic = float(importe)
            sum_adj = float(r.get("sum_adj") or 0.0)
            if imp_lic > 0:
                baja = float((1 - sum_adj / imp_lic) * 100)
        items.append(
            TopLicitacionItem(
                id_externo=str(r["id_externo"]),
                titulo=r.get("titulo"),
                organo_contratacion=r.get("organo_contratacion"),
                importe=float(importe) if importe is not None else None,
                estado=r.get("estado"),
                adjudicatario=r.get("adjudicatario"),
                baja_pct=baja,
            )
        )

    log.info("analytics_top_licitaciones_done", count=len(items))
    return TopLicitacionesResult(items=items)
