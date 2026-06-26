"""Ecosistema Partners — grafo de co-licitación REAL (UTE / co-adjudicación).

Wrapper de servicio sobre :func:`services.partners.build_partnership_graph` (que
opera sobre un DataFrame puro) + el loader canónico de adjudicaciones. Las aristas
empresa↔empresa existen **solo si han co-licitado** (UTE conjunta), con peso = nº de
contratos compartidos + importe — no co-ocurrencia geográfica por CCAA.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.partners import build_partnership_graph

log = get_logger(__name__)


class PartnerGraphFilters(BaseModel):
    """Filtros para el grafo de co-licitación."""

    ccaa: str | None = None  # comma-separated (multi-CCAA) desde el filtro global
    min_contratos: int = 1
    top_nodes: int = 20


class PartnerNode(BaseModel):
    """Nodo del grafo = empresa que ha co-licitado en UTE."""

    name: str
    contratos: int
    importe: float


class PartnerEdge(BaseModel):
    """Arista = co-licitación real (UTE conjunta); peso = nº contratos + importe."""

    source: str
    target: str
    contratos: int
    importe: float


class PartnershipGraphResult(BaseModel):
    """Grafo de co-licitación + nº de adjudicaciones UTE del dataset."""

    nodes: list[PartnerNode] = Field(default_factory=list)
    edges: list[PartnerEdge] = Field(default_factory=list)
    total_utes: int = 0


def get_partnership_graph(filters: PartnerGraphFilters) -> PartnershipGraphResult:
    """Grafo de co-licitación real (UTE), acotado en backend."""
    log.info("ecosistema_partners_start", filters=filters.model_dump(exclude_none=True))
    ccaa_filter = tuple(filters.ccaa.split(",")) if filters.ccaa else None
    df = pd.DataFrame(load_raw_adjudicaciones(ccaa_filter=ccaa_filter))
    if df.empty or "es_ute" not in df.columns:
        return PartnershipGraphResult()

    df["es_ute"] = df["es_ute"].fillna(0).astype(bool)
    total_utes = int(df["es_ute"].sum())

    graph = build_partnership_graph(
        df,
        min_contratos=filters.min_contratos,
        top_nodes=filters.top_nodes,
    )
    result = PartnershipGraphResult(
        nodes=[PartnerNode(**n) for n in graph["nodes"]],
        edges=[PartnerEdge(**e) for e in graph["edges"]],
        total_utes=total_utes,
    )
    log.info(
        "ecosistema_partners_done",
        nodes=len(result.nodes),
        edges=len(result.edges),
    )
    return result
