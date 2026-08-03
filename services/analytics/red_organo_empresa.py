"""Red Órgano-Empresa — grafo bipartito de adjudicaciones REALES.

Agrega en Postgres vía :class:`AdjudicacionRepository` (ADR-023): las aristas
(órgano, empresa) llegan YA agregadas del ``GROUP BY`` de
``organ_company_edges`` y el shaping del grafo (top-N, grados, frecuencia)
corre sobre ese resultado pequeño en
:func:`services.organ_company_graph.bipartite_graph_from_edge_aggregates` /
:func:`services.organ_concentration.organ_concentration_from_edge_aggregates`.
Hasta 2026-08 cada endpoint materializaba el join completo de adjudicaciones
en pandas — bloqueado en Render por el cortacircuitos full-table, que dejaba
estos 4 endpoints vacíos en producción. Las aristas representan
**adjudicaciones reales** (órgano → empresa adjudicataria), no co-localización
por CCAA; la identidad de empresa (maestro canónico con fallback al nombre
raw) vive en la expresión SQL del repositorio.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger
from services.organ_company_graph import bipartite_graph_from_edge_aggregates
from services.organ_concentration import organ_concentration_from_edge_aggregates

log = get_logger(__name__)

_repo = AdjudicacionRepository()


class GraphFilters(BaseModel):
    """Filtros para el grafo órgano-empresa."""

    ccaa: str | None = None  # comma-separated (multi-CCAA) desde el filtro global
    min_contratos: int = 1
    top_organos: int = 10
    top_empresas: int = 10


class GraphNode(BaseModel):
    """Nodo del grafo (órgano o empresa)."""

    name: str
    type: str  # "organo" | "empresa"
    degree: int
    importe_total: float
    key: str | None = None


class GraphEdge(BaseModel):
    """Arista = adjudicación real órgano → empresa (peso = nº/importe reales)."""

    organo: str
    empresa: str
    contratos: int
    importe_total: float
    frecuencia_anual: float


class OrganCompanyGraphResult(BaseModel):
    """Grafo bipartito órgano-empresa + totales del dataset completo."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    total_organos: int = 0
    total_empresas: int = 0


def _edges_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Aristas agregadas del repo → DataFrame con los tipos que el core espera.

    ``empresa_nombre`` == ``empresa_key`` a propósito: la expresión SQL ya
    resuelve maestro-canónico-o-raw, así que la clave ES el nombre mostrable.
    ``fecha_min``/``fecha_max`` se castean a datetime para la frecuencia anual.
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.assign(
        empresa_nombre=df["empresa_key"],
        importe_total=pd.to_numeric(df["importe_total"], errors="coerce").fillna(0.0),
        fecha_min=pd.to_datetime(df["fecha_min"], errors="coerce"),
        fecha_max=pd.to_datetime(df["fecha_max"], errors="coerce"),
    )


def _ccaa_tuple(ccaa: str | None) -> tuple[str, ...] | None:
    return tuple(ccaa.split(",")) if ccaa else None


def get_organ_company_graph(filters: GraphFilters) -> OrganCompanyGraphResult:
    """Grafo bipartito órgano↔empresa de adjudicaciones reales, acotado en backend."""
    log.info("red_organo_empresa_start", filters=filters.model_dump(exclude_none=True))
    ccaa_filter = _ccaa_tuple(filters.ccaa)
    edges = _edges_df(_repo.organ_company_edges(ccaa_filter=ccaa_filter))
    if edges.empty:
        return OrganCompanyGraphResult()

    total_organos, total_empresas = _repo.organ_company_totals(ccaa_filter=ccaa_filter)

    graph = bipartite_graph_from_edge_aggregates(
        edges,
        min_contratos=filters.min_contratos,
        top_organos=filters.top_organos,
        top_empresas=filters.top_empresas,
    )
    result = OrganCompanyGraphResult(
        nodes=[GraphNode(**n) for n in graph["nodes"]],
        edges=[GraphEdge(**e) for e in graph["edges"]],
        total_organos=total_organos,
        total_empresas=total_empresas,
    )
    log.info(
        "red_organo_empresa_done",
        nodes=len(result.nodes),
        edges=len(result.edges),
    )
    return result


# ---------------------------------------------------------------------------
# Concentración / incumbencia por órgano
# ---------------------------------------------------------------------------


class ConcentracionFilters(BaseModel):
    """Filtros para el ranking de concentración por órgano."""

    ccaa: str | None = None  # comma-separated (multi-CCAA) desde el filtro global
    min_contratos: int = 5
    top_n: int = 25


class OrganoConcentracion(BaseModel):
    """Estructura de la base de proveedores de un órgano."""

    organo: str
    n_empresas: int
    n_contratos: int
    importe_total: float
    top_empresa: str
    cuota_top1: float  # % de importe del proveedor líder
    cuota_top3: float  # % de importe acumulado del top-3 (CR3)
    hhi: float  # 0-10000
    apertura: str  # "Abierto" | "Moderado" | "Cerrado"


class ConcentracionResult(BaseModel):
    """Ranking de órganos por concentración de proveedores."""

    organos: list[OrganoConcentracion] = Field(default_factory=list)
    total_organos: int = 0


def get_organ_concentration(filters: ConcentracionFilters) -> ConcentracionResult:
    """Ranking de órganos por concentración de su base de proveedores (HHI)."""
    log.info("organ_concentration_start", filters=filters.model_dump(exclude_none=True))
    edges = _edges_df(_repo.organ_company_edges(ccaa_filter=_ccaa_tuple(filters.ccaa)))
    if edges.empty:
        return ConcentracionResult()

    data = organ_concentration_from_edge_aggregates(
        edges,
        min_contratos=filters.min_contratos,
        top_n=filters.top_n,
    )
    result = ConcentracionResult(
        organos=[OrganoConcentracion(**o) for o in data["organos"]],
        total_organos=data["total_organos"],
    )
    log.info("organ_concentration_done", organos=len(result.organos))
    return result


# ---------------------------------------------------------------------------
# Ego-network: vecindario de una entidad (órgano o empresa)
# ---------------------------------------------------------------------------


class EgoFilters(BaseModel):
    """Filtros para el ego-network órgano↔empresa."""

    ccaa: str | None = None
    entity_type: Literal["organo", "empresa"]
    entity_key: str
    top_neighbors: int = 30
    min_contratos: int = 1


def get_organ_company_ego(filters: EgoFilters) -> OrganCompanyGraphResult:
    """Vecindario inmediato de un órgano o empresa (grafo enfocado y legible)."""
    log.info("organ_company_ego_start", filters=filters.model_dump(exclude_none=True))
    ccaa_filter = _ccaa_tuple(filters.ccaa)
    if filters.entity_type == "organo":
        sub = _edges_df(
            _repo.organ_company_edges(ccaa_filter=ccaa_filter, organo=filters.entity_key)
        )
        graph = bipartite_graph_from_edge_aggregates(
            sub,
            min_contratos=filters.min_contratos,
            top_organos=1,
            top_empresas=filters.top_neighbors,
        )
    else:
        sub = _edges_df(
            _repo.organ_company_edges(ccaa_filter=ccaa_filter, empresa_key=filters.entity_key)
        )
        graph = bipartite_graph_from_edge_aggregates(
            sub,
            min_contratos=filters.min_contratos,
            top_organos=filters.top_neighbors,
            top_empresas=1,
        )

    total_organos, total_empresas = _repo.organ_company_totals(ccaa_filter=ccaa_filter)
    result = OrganCompanyGraphResult(
        nodes=[GraphNode(**n) for n in graph["nodes"]],
        edges=[GraphEdge(**e) for e in graph["edges"]],
        total_organos=total_organos,
        total_empresas=total_empresas,
    )
    log.info("organ_company_ego_done", nodes=len(result.nodes), edges=len(result.edges))
    return result


# ---------------------------------------------------------------------------
# Drill-down de arista: licitaciones que sustentan una relación organo-empresa
# ---------------------------------------------------------------------------


class EdgeDetailFilters(BaseModel):
    """Filtros para el detalle de una arista órgano→empresa."""

    ccaa: str | None = None
    organo: str
    empresa: str  # nombre canónico (== empresa_key)
    limit: int = 100


class EdgeLicitacion(BaseModel):
    """Licitación real detrás de una relación órgano→empresa."""

    licitacion_id: str | None = None
    titulo: str | None = None
    importe_adjudicado: float | None = None
    fecha_adjudicacion: str | None = None
    url: str | None = None


class EdgeDetailResult(BaseModel):
    """Licitaciones que sustentan una arista órgano→empresa."""

    organo: str
    empresa: str
    n_licitaciones: int = 0
    importe_total: float = 0.0
    licitaciones: list[EdgeLicitacion] = Field(default_factory=list)


def get_organ_company_edge(filters: EdgeDetailFilters) -> EdgeDetailResult:
    """Licitaciones reales que sustentan la relación órgano→empresa (drill-down)."""
    log.info(
        "organ_company_edge_start",
        organo=filters.organo,
        empresa=filters.empresa,
    )
    rows, n_licitaciones, importe_total = _repo.organ_company_edge_detail(
        organo=filters.organo,
        empresa_key=filters.empresa,
        ccaa_filter=_ccaa_tuple(filters.ccaa),
        limit=filters.limit,
    )
    if n_licitaciones == 0:
        return EdgeDetailResult(organo=filters.organo, empresa=filters.empresa)

    licitaciones = [
        EdgeLicitacion(
            licitacion_id=(str(r["licitacion_id"]) if r.get("licitacion_id") is not None else None),
            titulo=(str(r["titulo"]) if r.get("titulo") is not None else None),
            importe_adjudicado=(
                float(r["importe_adjudicado"]) if r.get("importe_adjudicado") is not None else None
            ),
            fecha_adjudicacion=(
                str(r["fecha_adjudicacion"]) if r.get("fecha_adjudicacion") is not None else None
            ),
            url=(str(r["url_lic"]) if r.get("url_lic") is not None else None),
        )
        for r in rows
    ]
    return EdgeDetailResult(
        organo=filters.organo,
        empresa=filters.empresa,
        n_licitaciones=n_licitaciones,
        importe_total=importe_total,
        licitaciones=licitaciones,
    )
