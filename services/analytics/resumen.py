"""Resumen analytics — novedades, hoy, timeline, sankey, top licitaciones."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


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


def _load_df() -> pd.DataFrame:
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["fecha_publicacion"] = pd.to_datetime(
            df["fecha_publicacion"],
            errors="coerce",
            utc=True,
        )
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
        if "fecha_limite" in df.columns:
            df["fecha_limite_dt"] = pd.to_datetime(
                df["fecha_limite"],
                errors="coerce",
                utc=True,
            )
    return df


def _apply_filters(df: pd.DataFrame, filters: Any) -> pd.DataFrame:
    if df.empty:
        return df
    if getattr(filters, "fecha_desde", None) is not None:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_publicacion"] >= ts]
    if getattr(filters, "fecha_hasta", None) is not None:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_publicacion"] <= ts]
    if getattr(filters, "ccaa", None):
        df = df[df["ccaa"] == filters.ccaa]
    if getattr(filters, "tecnologia", None):
        df = df[df["tecnologia"] == filters.tecnologia]
    return df


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

    df = _load_df()
    if df.empty:
        return ResumenNovedadesResult()

    ts = pd.to_datetime(last_login, errors="coerce", utc=True)
    if pd.isna(ts):
        return ResumenNovedadesResult()

    nuevas = df[df["fecha_publicacion"] > ts]
    count = len(nuevas)

    sample_df = nuevas.head(10)
    sample = [
        ResumenNovedadesSample(
            id_externo=str(row.get("id_externo", "")),
            titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
            importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
            organo_contratacion=(
                row.get("organo_contratacion") if pd.notna(row.get("organo_contratacion")) else None
            ),
        )
        for _, row in sample_df.iterrows()
    ]

    log.info("analytics_resumen_novedades_done", count=count)
    return ResumenNovedadesResult(count=count, sample=sample)


def get_resumen_hoy(filters: ResumenHoyFilters) -> ResumenHoyResult:
    """Para hoy — calientes, vencen 48h, nuevas 24h, total activas."""
    log.info("analytics_resumen_hoy_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        return ResumenHoyResult()

    hoy = pd.Timestamp.now("UTC")

    # Total activas
    activas = df[df["estado"].isin(["PUB", "EV"])]
    total_activas = len(activas)

    # Calientes: estado in (PUB, EV) AND importe >= P75 AND fecha_limite > now
    importes_validos = df["importe"].dropna()
    p75 = float(importes_validos.quantile(0.75)) if len(importes_validos) > 0 else 0.0
    calientes_mask = activas["importe"].ge(p75) & activas.get(
        "fecha_limite_dt", pd.Series(dtype="datetime64[ns, UTC]")
    ).gt(hoy)
    calientes = int(calientes_mask.sum()) if not calientes_mask.empty else 0

    # Vencen 48h
    vencen_48h = 0
    if "fecha_limite_dt" in df.columns:
        limite_48h = hoy + pd.Timedelta(hours=48)
        mask_48h = df["fecha_limite_dt"].between(hoy, limite_48h)
        vencen_48h = int(mask_48h.sum())

    # Nuevas 24h
    hace_24h = hoy - pd.Timedelta(hours=24)
    nuevas_24h = int((df["fecha_publicacion"] >= hace_24h).sum())

    result = ResumenHoyResult(
        calientes=calientes,
        vencen_48h=vencen_48h,
        nuevas_24h=nuevas_24h,
        total_activas=total_activas,
    )
    log.info("analytics_resumen_hoy_done")
    return result


def get_timeline_scatter(filters: TimelineScatterFilters) -> TimelineScatterResult:
    """Scatter data for all licitaciones (max 1000)."""
    log.info("analytics_timeline_scatter_start")
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        return TimelineScatterResult()

    df = df.sort_values("fecha_publicacion", ascending=False).head(1000)

    items = [
        TimelineScatterItem(
            id_externo=str(row.get("id_externo", "")),
            titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
            importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
            fecha_publicacion=(
                row["fecha_publicacion"].isoformat()
                if pd.notna(row.get("fecha_publicacion"))
                else None
            ),
            estado=row.get("estado") if pd.notna(row.get("estado")) else None,
            organo_contratacion=row.get("organo_contratacion")
            if pd.notna(row.get("organo_contratacion"))
            else None,
            tipo_contrato=row.get("tipo_contrato") if pd.notna(row.get("tipo_contrato")) else None,
            ccaa=row.get("ccaa") if pd.notna(row.get("ccaa")) else None,
        )
        for _, row in df.iterrows()
    ]

    log.info("analytics_timeline_scatter_done", count=len(items))
    return TimelineScatterResult(items=items)


def get_sankey_flow(filters: SankeyFilters) -> SankeyResult:
    """Sankey: tipo_contrato → estado transitions."""
    log.info("analytics_sankey_start")
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        return SankeyResult()

    if "tipo_contrato" not in df.columns or "estado" not in df.columns:
        return SankeyResult()

    work = df.dropna(subset=["tipo_contrato", "estado"])
    if work.empty:
        return SankeyResult()

    counts = work.groupby(["tipo_contrato", "estado"]).size().reset_index(name="value")

    # Build unique nodes
    tipos = sorted(work["tipo_contrato"].unique())
    estados = sorted(work["estado"].unique())
    nodes: list[SankeyNode] = []
    for t in tipos:
        nodes.append(SankeyNode(id=f"tipo_{t}", label=t))
    for e in estados:
        nodes.append(SankeyNode(id=f"estado_{e}", label=e))

    links = [
        SankeyLink(
            source=f"tipo_{row['tipo_contrato']}",
            target=f"estado_{row['estado']}",
            value=int(row["value"]),
        )
        for _, row in counts.iterrows()
    ]

    log.info("analytics_sankey_done", nodes=len(nodes), links=len(links))
    return SankeyResult(nodes=nodes, links=links)


def get_top_licitaciones(filters: TopLicitacionesFilters) -> TopLicitacionesResult:
    """Top N licitaciones by importe, enriched with adjudicatario info."""
    log.info("analytics_top_licitaciones_start", n=filters.n)
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        return TopLicitacionesResult()

    top = df.dropna(subset=["importe"]).nlargest(filters.n, "importe")

    # Load adjudicaciones for enrichment
    adj_rows = load_raw_adjudicaciones()
    adj_df = pd.DataFrame(adj_rows)

    adj_map: dict[str, tuple[str | None, float | None]] = {}
    if not adj_df.empty and "id_externo" in adj_df.columns:
        adj_name_col = "nombre" if "nombre" in adj_df.columns else "adjudicatario"
        if adj_name_col in adj_df.columns:
            for id_ext, grp in adj_df.groupby("id_externo"):
                nombre = (
                    grp[adj_name_col].dropna().iloc[0]
                    if not grp[adj_name_col].dropna().empty
                    else None
                )
                baja = None
                if "importe_adjudicado" in grp.columns and "importe_licitacion" in grp.columns:
                    imp_adj = pd.to_numeric(grp["importe_adjudicado"], errors="coerce").sum()
                    imp_lic = pd.to_numeric(grp["importe_licitacion"], errors="coerce").sum()
                    if imp_lic > 0 and pd.notna(imp_adj):
                        baja = float((1 - imp_adj / imp_lic) * 100)
                adj_map[str(id_ext)] = (str(nombre) if nombre else None, baja)

    items = []
    for _, row in top.iterrows():
        id_ext = str(row.get("id_externo", ""))
        adj_info = adj_map.get(id_ext, (None, None))
        items.append(
            TopLicitacionItem(
                id_externo=id_ext,
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                organo_contratacion=(
                    row.get("organo_contratacion")
                    if pd.notna(row.get("organo_contratacion"))
                    else None
                ),
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                estado=row.get("estado") if pd.notna(row.get("estado")) else None,
                adjudicatario=adj_info[0],
                baja_pct=adj_info[1],
            )
        )

    log.info("analytics_top_licitaciones_done", count=len(items))
    return TopLicitacionesResult(items=items)
