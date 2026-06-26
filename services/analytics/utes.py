"""UTE analytics — analysis of Uniones Temporales de Empresas."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.partners import build_partnership_graph

log = get_logger(__name__)


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

_UTE_PATTERN = r"(?i)UTE|UNION TEMPORAL|UNIÓN TEMPORAL"


def _load_df(ccaa: str | None) -> pd.DataFrame:
    ccaa_filter = (ccaa,) if ccaa else None
    rows = load_raw_adjudicaciones(ccaa_filter=ccaa_filter)
    df = pd.DataFrame(rows)
    if not df.empty:
        if "fecha_adjudicacion" in df.columns:
            df["fecha_adjudicacion"] = pd.to_datetime(
                df["fecha_adjudicacion"], errors="coerce", utc=True
            )
        df["importe"] = pd.to_numeric(
            df.get("importe_adjudicado", df.get("importe", pd.Series(dtype=float))),
            errors="coerce",
        )
        if "empresa" not in df.columns and "adjudicatario" in df.columns:
            df["empresa"] = df["adjudicatario"]
        elif "empresa" not in df.columns and "nombre" in df.columns:
            df["empresa"] = df["nombre"]
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_utes(filters: UTEFilters) -> UTEResult:
    """UTE-specific analysis from adjudicaciones."""
    log.info("analytics_utes_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df(filters.ccaa)

    if df.empty or "empresa" not in df.columns:
        return UTEResult()

    # Apply date filters
    if filters.fecha_desde is not None and "fecha_adjudicacion" in df.columns:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_adjudicacion"] >= ts]
    if filters.fecha_hasta is not None and "fecha_adjudicacion" in df.columns:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_adjudicacion"] <= ts]

    # Split UTE vs individual
    ute_mask = df["empresa"].str.contains(_UTE_PATTERN, na=False)
    ute_df = df[ute_mask]
    ind_df = df[~ute_mask]

    total_ute = len(ute_df)
    importe_ute = float(ute_df["importe"].sum(skipna=True))
    ticket_ute = (importe_ute / total_ute) if total_ute > 0 else 0.0

    total_ind = len(ind_df)
    importe_ind = float(ind_df["importe"].sum(skipna=True))
    ticket_ind = (importe_ind / total_ind) if total_ind > 0 else 0.0

    empresas_distintas = int(ute_df["empresa"].nunique()) if not ute_df.empty else 0

    kpis = UTEKpis(
        total_ute=total_ute,
        importe_ute=importe_ute,
        ticket_medio_ute=ticket_ute,
        ticket_medio_individual=ticket_ind,
        empresas_distintas=empresas_distintas,
    )

    # Top miembros (use full name since parsing UTE members is unreliable)
    top_miembros: list[UTEMiembro] = []
    if not ute_df.empty:
        g = (
            ute_df.groupby("empresa")
            .agg(count=("empresa", "count"), importe=("importe", "sum"))
            .sort_values("count", ascending=False)
            .head(20)
            .reset_index()
        )
        top_miembros = [
            UTEMiembro(
                nombre=str(row["empresa"]),
                count=int(row["count"]),
                importe=float(row["importe"] or 0),
            )
            for _, row in g.iterrows()
        ]

    # Evolucion mensual
    evolucion: list[UTEEvolucion] = []
    if not ute_df.empty and "fecha_adjudicacion" in ute_df.columns:
        work = ute_df.dropna(subset=["fecha_adjudicacion"]).copy()
        if not work.empty:
            work["period"] = work["fecha_adjudicacion"].dt.to_period("M").dt.to_timestamp()
            g = (
                work.groupby("period")
                .agg(contratos=("empresa", "count"), importe=("importe", "sum"))
                .reset_index()
                .sort_values("period")
            )
            evolucion = [
                UTEEvolucion(
                    period=row["period"].strftime("%Y-%m"),
                    contratos=int(row["contratos"]),
                    importe=float(row["importe"] or 0),
                )
                for _, row in g.iterrows()
            ]

    # Socios frecuentes: pares de empresas que han co-licitado en UTE (real,
    # parseado del nombre vía build_partnership_graph), ordenados por nº de UTEs.
    socios_frecuentes: list[UTESocioPar] = []
    if "es_ute" in df.columns and "nombre" in df.columns:
        gdf = df.copy()
        gdf["es_ute"] = gdf["es_ute"].fillna(0).astype(bool)
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
