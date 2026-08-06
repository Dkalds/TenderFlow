"""UTE analytics — analysis of Uniones Temporales de Empresas.

Agrega en Postgres vía :class:`AdjudicacionRepository` (ADR-023); hasta 2026-08
cargaba el join completo de adjudicaciones a pandas en el proceso API —
bloqueado en Render por el cortacircuitos full-table, que dejaba este endpoint
vacío en producción. El grafo de socios se construye sobre la proyección
ACOTADA de filas UTE (una fracción pequeña del total): además de acotar la
carga, esto REPARA ``socios_frecuentes`` — el camino anterior exigía una
columna ``es_ute`` que el loader raw nunca producía, así que la sección
llegaba siempre vacía.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger
from services.partners import build_partnership_graph

log = get_logger(__name__)

_repo = AdjudicacionRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class UTEFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None


class UTEKpis(BaseModel):
    total_ute: int = 0
    importe_ute: float = 0.0
    ticket_medio_ute: float = 0.0
    ticket_medio_individual: float = 0.0
    empresas_distintas: int = 0


class UTEMiembro(BaseModel):
    nombre: str
    count: int
    importe: float


class UTEEvolucion(BaseModel):
    period: str
    contratos: int
    importe: float


class UTETablaComparativa(BaseModel):
    count: int = 0
    importe_medio: float = 0.0
    importe_total: float = 0.0


class UTEComparacion(BaseModel):
    ute: UTETablaComparativa = Field(default_factory=UTETablaComparativa)
    individual: UTETablaComparativa = Field(default_factory=UTETablaComparativa)


class UTESocioPar(BaseModel):
    """Par de empresas que han co-licitado en UTE (quién se asocia con quién)."""

    empresa_a: str
    empresa_b: str
    contratos: int
    importe: float


class UTEResult(BaseModel):
    kpis: UTEKpis = Field(default_factory=UTEKpis)
    top_miembros: list[UTEMiembro] = Field(default_factory=list)
    socios_frecuentes: list[UTESocioPar] = Field(default_factory=list)
    evolucion: list[UTEEvolucion] = Field(default_factory=list)
    tabla_comparativa: UTEComparacion = Field(default_factory=UTEComparacion)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# Aplicado con `~*` (regex POSIX case-insensitive de Postgres) sobre el nombre
# raw del adjudicatario. Los `\y` son límites de palabra: sin ellos el token
# `UTE` matcheaba como substring dentro de cualquier palabra ("COMPUTER",
# "COMPLUTENSE", "SALUTEM"…), inflando total_ute/importe_ute sobre un corpus que
# es puro IT. (El camino robusto sería `empresas.es_ute` del maestro v35, como
# hace services/competitive/mercado.py; esto acota el falso positivo sin
# depender de la resolución de identidad.)
_UTE_PATTERN = r"\yUTE\y|\yUNI[OÓ]N TEMPORAL\y"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_utes(filters: UTEFilters) -> UTEResult:
    """UTE-specific analysis from adjudicaciones."""
    log.info("analytics_utes_start", filters=filters.model_dump(exclude_none=True))
    ccaa_filter = (filters.ccaa,) if filters.ccaa else None
    fecha_desde = filters.fecha_desde.isoformat() if filters.fecha_desde else None
    fecha_hasta = filters.fecha_hasta.isoformat() if filters.fecha_hasta else None

    stats = _repo.ute_kpis(
        pattern=_UTE_PATTERN,
        ccaa_filter=ccaa_filter,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )

    total_ute = stats["total_ute"]
    importe_ute = stats["importe_ute"]
    ticket_ute = (importe_ute / total_ute) if total_ute > 0 else 0.0

    total_ind = stats["total_individual"]
    importe_ind = stats["importe_individual"]
    ticket_ind = (importe_ind / total_ind) if total_ind > 0 else 0.0

    kpis = UTEKpis(
        total_ute=total_ute,
        importe_ute=importe_ute,
        ticket_medio_ute=ticket_ute,
        ticket_medio_individual=ticket_ind,
        empresas_distintas=stats["empresas_distintas"],
    )

    # Top miembros (use full name since parsing UTE members is unreliable)
    top_miembros = [
        UTEMiembro(
            nombre=str(r["nombre"]),
            count=int(r["count"]),
            importe=float(r["importe"] or 0),
        )
        for r in _repo.ute_top_miembros(
            pattern=_UTE_PATTERN,
            ccaa_filter=ccaa_filter,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            limit=20,
        )
    ]

    # Evolucion mensual
    evolucion = [
        UTEEvolucion(
            period=str(r["period"]),
            contratos=int(r["contratos"]),
            importe=float(r["importe"] or 0),
        )
        for r in _repo.ute_evolucion(
            pattern=_UTE_PATTERN,
            ccaa_filter=ccaa_filter,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
    ]

    # Socios frecuentes: pares de empresas que han co-licitado en UTE (real,
    # parseado del nombre vía build_partnership_graph sobre la proyección
    # acotada de filas UTE), ordenados por nº de UTEs.
    socios_frecuentes: list[UTESocioPar] = []
    ute_rows = _repo.load_ute_rows(
        pattern=_UTE_PATTERN,
        ccaa_filter=ccaa_filter,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
    )
    if ute_rows:
        gdf = pd.DataFrame(ute_rows).assign(es_ute=True)
        graph = build_partnership_graph(gdf, min_contratos=1, top_nodes=80)
        top_edges = sorted(graph["edges"], key=lambda e: e["contratos"], reverse=True)[:20]
        socios_frecuentes = [
            UTESocioPar(
                empresa_a=str(e["source"]),
                empresa_b=str(e["target"]),
                contratos=int(e["contratos"]),
                importe=float(e["importe"]),
            )
            for e in top_edges
        ]

    # Tabla comparativa
    tabla = UTEComparacion(
        ute=UTETablaComparativa(
            count=total_ute,
            importe_medio=ticket_ute,
            importe_total=importe_ute,
        ),
        individual=UTETablaComparativa(
            count=total_ind,
            importe_medio=ticket_ind,
            importe_total=importe_ind,
        ),
    )

    log.info("analytics_utes_done", total_ute=total_ute)
    return UTEResult(
        kpis=kpis,
        top_miembros=top_miembros,
        socios_frecuentes=socios_frecuentes,
        evolucion=evolucion,
        tabla_comparativa=tabla,
    )
