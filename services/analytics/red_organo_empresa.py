"""Red Órgano-Empresa — grafo bipartito de adjudicaciones REALES.

Wrapper de servicio sobre :func:`services.organ_company_graph.build_bipartite_graph`
(que opera sobre un DataFrame puro) + el loader canónico de adjudicaciones. Expone
nodos/aristas tipados para el endpoint. Las aristas representan **adjudicaciones
reales** (órgano → empresa adjudicataria), no co-localización por CCAA.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.organ_company_graph import build_bipartite_graph

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
