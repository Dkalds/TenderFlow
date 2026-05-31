"""Competitor analytics — market share, HHI, bidder rankings."""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class CompetitorFilters(BaseModel):
    """Query filters for competitor analysis."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    limit: int = 20


class CompetitorEntry(BaseModel):
    """Single competitor entry."""

    nombre: str
    count: int
    importe: float
    cuota: float
    nif: str | None = None
    contratos_por_anio: float = 0.0
    importe_medio: float = 0.0
    baja_media: float | None = None
    n_organos: int = 0
    ofertas_medias: float | None = None
    pct_monopolio: float = 0.0
    pct_top_organo: float = 0.0
    ultima: str | None = None


class ScatterPoint(BaseModel):
    """Scatter data point for competitors."""

    nombre: str
    ticket_medio: float
    n_organos: int


class HeatmapCcaaCell(BaseModel):
    """Heatmap cell: empresa x CCAA."""

    ccaa: str
    empresa: str
    count: int


class EstacionalidadEntry(BaseModel):
    """Monthly seasonality entry."""

    mes: int
    count: int
    importe: float


class CompetitorResult(BaseModel):
    """Combined competitor response."""

    competitors: list[CompetitorEntry] = Field(default_factory=list)
    hhi: float = 0.0
    pct_oferta_unica: float = 0.0
    total_adjudicaciones: int = 0
    scatter_data: list[ScatterPoint] = Field(default_factory=list)
    heatmap_ccaa: list[HeatmapCcaaCell] = Field(default_factory=list)
    pct_pyme: float = 0.0
    estacionalidad: list[EstacionalidadEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df(ccaa: str | None) -> pd.DataFrame:
    ccaa_filter = (ccaa,) if ccaa else None
    rows = load_raw_adjudicaciones(ccaa_filter=ccaa_filter)
    df = pd.DataFrame(rows)
    if not df.empty:
        if "fecha_adjudicacion" in df.columns:
            df["fecha_adjudicacion"] = pd.to_datetime(
                df["fecha_adjudicacion"],
                errors="coerce",
                utc=True,
            )
        df["importe"] = pd.to_numeric(
            df.get(
                "importe_adjudicado",
                df.get("importe_adjudicacion", df.get("importe", pd.Series(dtype=float))),
            ),
            errors="coerce",
        )
        if "empresa" not in df.columns:
            if "adjudicatario" in df.columns:
                df["empresa"] = df["adjudicatario"]
            elif "nombre" in df.columns:
                df["empresa"] = df["nombre"]
    return df


def _apply_filters(df: pd.DataFrame, filters: CompetitorFilters) -> pd.DataFrame:
    if df.empty:
        return df
    if filters.fecha_desde is not None and "fecha_adjudicacion" in df.columns:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_adjudicacion"] >= ts]
    if filters.fecha_hasta is not None and "fecha_adjudicacion" in df.columns:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_adjudicacion"] <= ts]
    return df


def _compute_hhi(shares: pd.Series) -> float:  # type: ignore[type-arg]
    """Herfindahl-Hirschman Index from market share percentages (0-10000)."""
    return float((shares**2).sum())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_competitors(filters: CompetitorFilters) -> CompetitorResult:
    """Compute competitor rankings, HHI, and single-bid percentage."""
    log.info("analytics_competitors_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df(filters.ccaa)
    df = _apply_filters(df, filters)

    if df.empty or "empresa" not in df.columns:
        log.info("analytics_competitors_done", total=0)
        return CompetitorResult()

    total = len(df)

    # Group by empresa
    g = (
        df.groupby("empresa")
        .agg(count=("empresa", "count"), importe=("importe", "sum"))
        .sort_values("count", ascending=False)
        .reset_index()
    )

    total_importe = float(g["importe"].sum(skipna=True)) or 1.0
    g["cuota"] = g["importe"] / total_importe * 100

    # Compute extra fields
    n_years = 1
    if "fecha_adjudicacion" in df.columns:
        years = df["fecha_adjudicacion"].dropna().dt.year.nunique()
        n_years = max(years, 1)

    # baja_media per empresa
    baja_by_empresa: dict[str, float] = {}
    if "importe_adjudicado" in df.columns and "importe_licitacion" in df.columns:
        imp_adj = pd.to_numeric(df.get("importe_adjudicado"), errors="coerce")
        imp_lic = pd.to_numeric(df.get("importe_licitacion"), errors="coerce")
        df_baja = df.copy()
        df_baja["_baja"] = ((1 - imp_adj / imp_lic) * 100).where((imp_lic > 0) & imp_adj.notna())
        baja_means = df_baja.groupby("empresa")["_baja"].mean()
        baja_by_empresa = {k: float(v) for k, v in baja_means.items() if pd.notna(v)}

    # nif per empresa
    nif_by_empresa: dict[str, str] = {}
    if "nif" in df.columns:
        nif_first = df.dropna(subset=["nif"]).groupby("empresa")["nif"].first()
        nif_by_empresa = {k: str(v) for k, v in nif_first.items()}

    # n_organos per empresa
    n_organos_map: dict[str, int] = {}
    if "organo_contratacion" in df.columns:
        n_organos_map = df.groupby("empresa")["organo_contratacion"].nunique().to_dict()

    # ofertas_medias per empresa
    ofertas_map: dict[str, float] = {}
    if "n_ofertas_recibidas" in df.columns:
        _ofertas = pd.to_numeric(df["n_ofertas_recibidas"], errors="coerce")
        _df_of = df.assign(_ofertas=_ofertas)
        ofertas_map = {
            k: float(v)
            for k, v in _df_of.groupby("empresa")["_ofertas"].mean().items()
            if pd.notna(v)
        }

    # pct_monopolio per empresa (% licitaciones where empresa was only bidder)
    lic_id_col = "id_externo" if "id_externo" in df.columns else "licitacion_id"
    pct_monopolio_map: dict[str, float] = {}
    if lic_id_col in df.columns:
        bids_per_lic = df.groupby(lic_id_col)["empresa"].nunique()
        single_bid_lics = set(bids_per_lic[bids_per_lic == 1].index)
        for emp_name, emp_sub in df.groupby("empresa"):
            emp_lics = emp_sub[lic_id_col].unique()
            total_emp = len(emp_lics)
            mono = sum(1 for lic in emp_lics if lic in single_bid_lics)
            pct_monopolio_map[str(emp_name)] = (mono / total_emp * 100) if total_emp > 0 else 0.0

    # pct_top_organo per empresa (% from their most common organo)
    pct_top_organo_map: dict[str, float] = {}
    if "organo_contratacion" in df.columns:
        for emp_name, emp_sub in df.groupby("empresa"):
            org_counts = emp_sub["organo_contratacion"].value_counts()
            if not org_counts.empty and len(emp_sub) > 0:
                pct_top_organo_map[str(emp_name)] = float(org_counts.iloc[0] / len(emp_sub) * 100)

    # ultima adjudicacion per empresa
    ultima_map: dict[str, str] = {}
    if "fecha_adjudicacion" in df.columns:
        for emp_name, emp_sub in df.groupby("empresa"):
            last = emp_sub["fecha_adjudicacion"].dropna().max()
            if pd.notna(last):
                ultima_map[str(emp_name)] = str(last.strftime("%Y-%m-%d"))

    entries = [
        CompetitorEntry(
            nombre=row["empresa"],
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
            cuota=float(row["cuota"]),
            nif=nif_by_empresa.get(row["empresa"]),
            contratos_por_anio=float(row["count"]) / n_years,
            importe_medio=float(row["importe"] or 0) / max(int(row["count"]), 1),
            baja_media=baja_by_empresa.get(row["empresa"]),
            n_organos=int(n_organos_map.get(row["empresa"], 0)),
            ofertas_medias=ofertas_map.get(row["empresa"]),
            pct_monopolio=pct_monopolio_map.get(row["empresa"], 0.0),
            pct_top_organo=pct_top_organo_map.get(row["empresa"], 0.0),
            ultima=ultima_map.get(row["empresa"]),
        )
        for _, row in g.head(filters.limit).iterrows()
    ]

    hhi = _compute_hhi(g["cuota"])

    # Single-bid percentage: licitaciones with only one bidder
    pct_unica = 0.0
    if lic_id_col in df.columns:
        bids_per_lic = df.groupby(lic_id_col)["empresa"].nunique()
        single_bid = int((bids_per_lic == 1).sum())
        total_lics = len(bids_per_lic)
        pct_unica = (single_bid / total_lics * 100) if total_lics else 0.0

    # Scatter data: ticket_medio vs n_organos
    scatter_data: list[ScatterPoint] = []
    for _, row in g.head(filters.limit).iterrows():
        ticket = float(row["importe"] or 0) / max(int(row["count"]), 1)
        n_organos = 1
        if "organo_contratacion" in df.columns:
            emp_df = df[df["empresa"] == row["empresa"]]
            n_organos = int(emp_df["organo_contratacion"].nunique())
        scatter_data.append(
            ScatterPoint(nombre=row["empresa"], ticket_medio=ticket, n_organos=n_organos)
        )

    # Heatmap: top 10 empresas x CCAAs
    heatmap_ccaa: list[HeatmapCcaaCell] = []
    if "ccaa" in df.columns:
        top10_empresas = g.head(10)["empresa"].tolist()
        hm_df = df[df["empresa"].isin(top10_empresas)]
        hm_counts = hm_df.groupby(["ccaa", "empresa"]).size().reset_index(name="count")
        heatmap_ccaa = [
            HeatmapCcaaCell(ccaa=str(r["ccaa"]), empresa=str(r["empresa"]), count=int(r["count"]))
            for _, r in hm_counts.iterrows()
        ]

    # pct_pyme
    pct_pyme = 0.0
    if "es_pyme" in df.columns:
        pyme_vals = pd.to_numeric(df["es_pyme"], errors="coerce").fillna(0)
        pct_pyme = float(pyme_vals.astype(bool).sum() / len(df) * 100) if len(df) > 0 else 0.0

    # estacionalidad mensual
    estacionalidad: list[EstacionalidadEntry] = []
    if "fecha_adjudicacion" in df.columns:
        monthly = df.dropna(subset=["fecha_adjudicacion"]).copy()
        if not monthly.empty:
            monthly["_mes"] = monthly["fecha_adjudicacion"].dt.month
            agg_m = (
                monthly.groupby("_mes")
                .agg(_count=("empresa", "count"), _importe=("importe", "sum"))
                .reset_index()
            )
            estacionalidad = [
                EstacionalidadEntry(
                    mes=int(r["_mes"]),
                    count=int(r["_count"]),
                    importe=float(r["_importe"] or 0),
                )
                for _, r in agg_m.iterrows()
            ]

    result = CompetitorResult(
        competitors=entries,
        hhi=hhi,
        pct_oferta_unica=pct_unica,
        total_adjudicaciones=total,
        scatter_data=scatter_data,
        heatmap_ccaa=heatmap_ccaa,
        pct_pyme=pct_pyme,
        estacionalidad=estacionalidad,
    )
    log.info("analytics_competitors_done", total=total, hhi=hhi)
    return result
