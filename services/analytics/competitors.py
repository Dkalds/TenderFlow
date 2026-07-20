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
    tecnologia: str | None = None
    estado: str | None = None
    importe_min: float | None = None
    limit: int = 20


class CompetitorEntry(BaseModel):
    """Single competitor entry."""

    nombre: str
    count: int
    importe: float
    cuota: float
    empresa_id: int | None = None
    nif: str | None = None
    contratos_por_anio: float = 0.0
    importe_medio: float = 0.0
    baja_media: float | None = None
    n_organos: int = 0
    ofertas_medias: float | None = None
    pct_monopolio: float | None = None
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
    total_empresas: int = 0
    importe_total: float = 0.0
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
        # Clave de agrupación canónica: nombre del maestro de empresas (v35),
        # con fallback al nombre crudo del adjudicatario. Sin esto las cuotas y
        # el HHI se fragmentan entre variantes del mismo adjudicatario
        # ("Accenture S.L." vs "Accenture, S.L.U." cuentan como dos).
        raw_name = df["adjudicatario"] if "adjudicatario" in df.columns else df.get("nombre")
        master_name = df.get("empresa_nombre_master")
        if master_name is not None and raw_name is not None:
            df["empresa"] = master_name.where(
                master_name.notna() & (master_name.astype(str) != ""), raw_name
            )
        elif master_name is not None:
            df["empresa"] = master_name
        elif raw_name is not None:
            df["empresa"] = raw_name
        # NIF: preferir el canónico del maestro sobre el de la adjudicación.
        master_nif = df.get("empresa_nif_master")
        if master_nif is not None:
            base_nif = df["nif"] if "nif" in df.columns else None
            df["nif"] = (
                master_nif.where(master_nif.notna() & (master_nif.astype(str) != ""), base_nif)
                if base_nif is not None
                else master_nif
            )
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
    # Eje de producto: segmentación por tecnología (SAP, Salesforce, …).
    if filters.tecnologia and "tecnologia" in df.columns:
        df = df[df["tecnologia"] == filters.tecnologia]
    if filters.estado and "estado" in df.columns:
        df = df[df["estado"] == filters.estado]
    if filters.importe_min is not None and "importe_licitacion" in df.columns:
        imp = pd.to_numeric(df["importe_licitacion"], errors="coerce")
        df = df[imp >= filters.importe_min]
    return df


def _compute_hhi(shares: pd.Series) -> float:
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
    active_years_by_empresa: dict[str, int] = {}
    if "fecha_adjudicacion" in df.columns:
        dated = df.dropna(subset=["fecha_adjudicacion"]).copy()
        if not dated.empty:
            dated["_activity_year"] = dated["fecha_adjudicacion"].dt.year
            active_years_by_empresa = {
                str(key): max(int(value), 1)
                for key, value in dated.groupby("empresa")["_activity_year"].nunique().items()
            }

    # baja_media per empresa
    baja_by_empresa: dict[str, float] = {}
    if "importe_adjudicado" in df.columns and "importe_licitacion" in df.columns:
        adj_col = df.get("importe_adjudicado")
        lic_col = df.get("importe_licitacion")
        if adj_col is not None and lic_col is not None:
            imp_adj = pd.to_numeric(adj_col, errors="coerce")
            imp_lic = pd.to_numeric(lic_col, errors="coerce")
            df_baja = df.copy()
            df_baja["_baja"] = ((1 - imp_adj / imp_lic) * 100).where(
                (imp_lic > 0) & imp_adj.notna()
            )
            baja_means = df_baja.groupby("empresa")["_baja"].mean()
            baja_by_empresa = {str(k): float(v) for k, v in baja_means.items() if pd.notna(v)}

    # nif per empresa
    nif_by_empresa: dict[str, str] = {}
    if "nif" in df.columns:
        nif_first = df.dropna(subset=["nif"]).groupby("empresa")["nif"].first()
        nif_by_empresa = {str(k): str(v) for k, v in nif_first.items()}

    # empresa_id canónico per empresa (para enlazar perfil / watchlist)
    empresa_id_map: dict[str, int] = {}
    if "empresa_id" in df.columns:
        eid_first = df.dropna(subset=["empresa_id"]).groupby("empresa")["empresa_id"].first()
        empresa_id_map = {str(k): int(v) for k, v in eid_first.items() if pd.notna(v)}

    # n_organos per empresa
    n_organos_map: dict[str, int] = {}
    if "organo_contratacion" in df.columns:
        n_organos_map = {
            str(k): int(v)
            for k, v in df.groupby("empresa")["organo_contratacion"].nunique().to_dict().items()
        }

    # ofertas_medias per empresa
    ofertas_map: dict[str, float] = {}
    if "n_ofertas_recibidas" in df.columns:
        _ofertas = pd.to_numeric(df["n_ofertas_recibidas"], errors="coerce")
        _df_of = df.assign(_ofertas=_ofertas)
        ofertas_map = {
            str(k): float(v)
            for k, v in _df_of.groupby("empresa")["_ofertas"].mean().items()
            if pd.notna(v)
        }

    # Señal de "oferta única" basada en el número REAL de ofertantes
    # (``n_ofertas_recibidas``), no en el nº de adjudicatarios: la tabla
    # ``adjudicaciones`` solo contiene ganadores, así que contar adjudicatarios
    # distintos por licitación da ~1 siempre y no mide competencia. Solo se
    # consideran licitaciones que reportan el dato (cobertura parcial según fuente).
    lic_id_col = "id_externo" if "id_externo" in df.columns else "licitacion_id"
    single_bid_lics: set[object] = set()
    lics_con_ofertas: set[object] = set()
    if lic_id_col in df.columns and "n_ofertas_recibidas" in df.columns:
        _ofertas_lic = pd.to_numeric(df["n_ofertas_recibidas"], errors="coerce")
        _per_lic = df.assign(_ofertas=_ofertas_lic).dropna(subset=["_ofertas"])
        ofertas_por_lic = _per_lic.groupby(lic_id_col)["_ofertas"].max()
        lics_con_ofertas = set(ofertas_por_lic.index)
        single_bid_lics = set(ofertas_por_lic[ofertas_por_lic <= 1].index)

    # pct_monopolio per empresa (% de sus licitaciones —con dato— sin rival)
    pct_monopolio_map: dict[str, float | None] = {}
    if lic_id_col in df.columns:
        for emp_name, emp_sub in df.groupby("empresa"):
            emp_lics = set(emp_sub[lic_id_col].unique()) & lics_con_ofertas
            total_emp = len(emp_lics)
            if total_emp == 0:
                pct_monopolio_map[str(emp_name)] = None  # sin cobertura → desconocido
                continue
            mono = len(emp_lics & single_bid_lics)
            pct_monopolio_map[str(emp_name)] = mono / total_emp * 100

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
            empresa_id=empresa_id_map.get(row["empresa"]),
            nif=nif_by_empresa.get(row["empresa"]),
            contratos_por_anio=float(row["count"])
            / active_years_by_empresa.get(str(row["empresa"]), 1),
            importe_medio=float(row["importe"] or 0) / max(int(row["count"]), 1),
            baja_media=baja_by_empresa.get(row["empresa"]),
            n_organos=int(n_organos_map.get(row["empresa"], 0)),
            ofertas_medias=ofertas_map.get(row["empresa"]),
            pct_monopolio=pct_monopolio_map.get(row["empresa"]),
            pct_top_organo=pct_top_organo_map.get(row["empresa"], 0.0),
            ultima=ultima_map.get(row["empresa"]),
        )
        for _, row in g.head(filters.limit).iterrows()
    ]

    hhi = _compute_hhi(g["cuota"])

    # % de licitaciones con un solo ofertante (sobre las que reportan
    # ``n_ofertas_recibidas``). Bandera roja clásica de contratación pública.
    total_lics = len(lics_con_ofertas)
    pct_unica = (len(single_bid_lics) / total_lics * 100) if total_lics else 0.0

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

    # Desglose CCAA x empresa para las empresas listadas (``filters.limit``).
    # El heatmap del front muestra su propio top 10, pero el drill-down de
    # cualquier competidor de la tabla necesita su desglose: limitar a 10 aquí
    # dejaba vacío el panel de detalle para las posiciones 11..N.
    heatmap_ccaa: list[HeatmapCcaaCell] = []
    if "ccaa" in df.columns:
        listed_empresas = g.head(filters.limit)["empresa"].tolist()
        hm_df = df[df["empresa"].isin(listed_empresas)]
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
        total_empresas=len(g),
        importe_total=total_importe,
        scatter_data=scatter_data,
        heatmap_ccaa=heatmap_ccaa,
        pct_pyme=pct_pyme,
        estacionalidad=estacionalidad,
    )
    log.info("analytics_competitors_done", total=total, hhi=hhi)
    return result
