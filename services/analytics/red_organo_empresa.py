"""Red Órgano-Empresa — grafo bipartito de adjudicaciones REALES.

Wrapper de servicio sobre :func:`services.organ_company_graph.build_bipartite_graph`
(que opera sobre un DataFrame puro) + el loader canónico de adjudicaciones. Expone
nodos/aristas tipados para el endpoint. Las aristas representan **adjudicaciones
reales** (órgano → empresa adjudicataria), no co-localización por CCAA.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.organ_company_graph import build_bipartite_graph
from services.organ_concentration import build_organ_concentration

log = get_logger(__name__)


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


def _prepare_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Construye las columnas que ``build_bipartite_graph`` espera.

    ``nombre_canonico`` = nombre canónico de la empresa (resolución de entidades)
    o, si no está resuelta, el nombre raw del adjudicatario. ``empresa_key`` usa el
    mismo valor (la canonicalización ya colapsa variantes). ``fecha_adjudicacion``
    se castea a datetime para el cálculo de frecuencia anual.
    """
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    raw = df["nombre"] if "nombre" in df.columns else pd.Series([None] * len(df), index=df.index)
    if "empresa_nombre_master" in df.columns:
        master = df["empresa_nombre_master"]
        valid_master = master.notna() & (master.astype(str).str.strip() != "")
        df["nombre_canonico"] = master.where(valid_master, raw)
    else:
        df["nombre_canonico"] = raw
    df["empresa_key"] = df["nombre_canonico"]
    if "fecha_adjudicacion" in df.columns:
        df["fecha_adjudicacion"] = pd.to_datetime(df["fecha_adjudicacion"], errors="coerce")
    return df


def get_organ_company_graph(filters: GraphFilters) -> OrganCompanyGraphResult:
    """Grafo bipartito órgano↔empresa de adjudicaciones reales, acotado en backend."""
    log.info("red_organo_empresa_start", filters=filters.model_dump(exclude_none=True))
    ccaa_filter = tuple(filters.ccaa.split(",")) if filters.ccaa else None
    df = _prepare_df(load_raw_adjudicaciones(ccaa_filter=ccaa_filter))
    if df.empty:
        return OrganCompanyGraphResult()

    total_organos = (
        int(df["organo_contratacion"].dropna().nunique())
        if "organo_contratacion" in df.columns
        else 0
    )
    total_empresas = int(df["empresa_key"].dropna().nunique())

    graph = build_bipartite_graph(
        df,
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
    ccaa_filter = tuple(filters.ccaa.split(",")) if filters.ccaa else None
    df = _prepare_df(load_raw_adjudicaciones(ccaa_filter=ccaa_filter))
    if df.empty:
        return ConcentracionResult()

    data = build_organ_concentration(
        df,
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
    ccaa_filter = tuple(filters.ccaa.split(",")) if filters.ccaa else None
    df = _prepare_df(load_raw_adjudicaciones(ccaa_filter=ccaa_filter))
    if df.empty:
        return OrganCompanyGraphResult()

    if filters.entity_type == "organo":
        sub = df[df["organo_contratacion"] == filters.entity_key]
        graph = build_bipartite_graph(
            sub,
            min_contratos=filters.min_contratos,
            top_organos=1,
            top_empresas=filters.top_neighbors,
        )
    else:
        sub = df[df["empresa_key"] == filters.entity_key]
        graph = build_bipartite_graph(
            sub,
            min_contratos=filters.min_contratos,
            top_organos=filters.top_neighbors,
            top_empresas=1,
        )

    result = OrganCompanyGraphResult(
        nodes=[GraphNode(**n) for n in graph["nodes"]],
        edges=[GraphEdge(**e) for e in graph["edges"]],
        total_organos=int(df["organo_contratacion"].dropna().nunique()),
        total_empresas=int(df["empresa_key"].dropna().nunique()),
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
    empresa: str  # nombre_canonico (== empresa_key)
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
    ccaa_filter = tuple(filters.ccaa.split(",")) if filters.ccaa else None
    df = _prepare_df(load_raw_adjudicaciones(ccaa_filter=ccaa_filter))
    if df.empty:
        return EdgeDetailResult(organo=filters.organo, empresa=filters.empresa)

    sub = df[
        (df["organo_contratacion"] == filters.organo) & (df["empresa_key"] == filters.empresa)
    ].copy()
    if sub.empty:
        return EdgeDetailResult(organo=filters.organo, empresa=filters.empresa)

    sub["importe_adjudicado"] = pd.to_numeric(sub["importe_adjudicado"], errors="coerce")
    sub = sub.sort_values("importe_adjudicado", ascending=False, na_position="last")

    def _iso(v: Any) -> str | None:
        if pd.isna(v):
            return None
        try:
            return pd.Timestamp(v).date().isoformat()
        except (ValueError, TypeError):
            return str(v)

    licitaciones = [
        EdgeLicitacion(
            licitacion_id=(str(r["licitacion_id"]) if pd.notna(r.get("licitacion_id")) else None),
            titulo=(str(r["titulo"]) if pd.notna(r.get("titulo")) else None),
            importe_adjudicado=(
                float(r["importe_adjudicado"]) if pd.notna(r.get("importe_adjudicado")) else None
            ),
            fecha_adjudicacion=_iso(r.get("fecha_adjudicacion")),
            url=(str(r["url_lic"]) if pd.notna(r.get("url_lic")) else None),
        )
        for _, r in sub.head(filters.limit).iterrows()
    ]
    return EdgeDetailResult(
        organo=filters.organo,
        empresa=filters.empresa,
        n_licitaciones=len(sub),
        importe_total=float(sub["importe_adjudicado"].sum(skipna=True)),
        licitaciones=licitaciones,
    )
