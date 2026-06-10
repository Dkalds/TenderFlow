"""Tecnologias analytics — technology distribution, cross-tabs and detail.

Explodes comma-separated technologies, maps them to readable labels and
exposes KPIs, cross-dimensional breakdowns (organo / geografia / evolucion)
and per-technology tender detail for the application layer.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.classification import estado_label, tecnologia_label
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)

# Bounds to keep payloads small / charts readable.
_TOP_ORGANOS = 10
_TOP_CCAA = 10
_TOP_TECHS_CROSS = 10
_TOP_TECHS_EVOL = 8
_ADJ_ESTADO = "ADJ"
_OTRAS = "Otras"


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TecnologiasFilters(BaseModel):
    """Query filters for the tecnologias endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None


class TecnologiaEntry(BaseModel):
    """Single technology aggregate (keyed by readable label)."""

    tecnologia: str
    count: int
    importe: float
    importe_medio: float
    pct: float
    pct_adjudicado: float


class CrossOrganoEntry(BaseModel):
    """tecnologia x organo cell."""

    organo: str
    tecnologia: str
    count: int


class CrossGeoEntry(BaseModel):
    """tecnologia x ccaa cell."""

    ccaa: str
    tecnologia: str
    count: int


class EvolucionEntry(BaseModel):
    """Monthly point for a technology."""

    mes: str
    tecnologia: str
    count: int
    importe: float


class TecnologiasResult(BaseModel):
    """Combined tecnologias response."""

    tecnologias: list[TecnologiaEntry] = Field(default_factory=list)
    sin_clasificar: int = 0
    # KPIs
    n_tecnologias: int = 0
    tecnologia_lider: str | None = None
    lider_count: int = 0
    importe_medio_global: float = 0.0
    tasa_adjudicacion_media: float = 0.0
    # Cross-tabs
    cross_organo: list[CrossOrganoEntry] = Field(default_factory=list)
    cross_geo: list[CrossGeoEntry] = Field(default_factory=list)
    evolucion_mensual: list[EvolucionEntry] = Field(default_factory=list)


class TecnologiaDetalleFilters(BaseModel):
    """Query filters for the per-technology detail endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    limit: int = 100


class TecnologiaDetalleItem(BaseModel):
    """Single tender row in the detail table."""

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    estado: str | None = None
    ccaa: str | None = None
    fecha_publicacion: str | None = None


class TecnologiaDetalleResult(BaseModel):
    """Detail payload for a single technology."""

    tecnologia: str
    n: int = 0
    importe_total: float = 0.0
    importe_medio: float = 0.0
    items: list[TecnologiaDetalleItem] = Field(default_factory=list)


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
    return df


def _apply_filters(
    df: pd.DataFrame, filters: TecnologiasFilters | TecnologiaDetalleFilters
) -> pd.DataFrame:
    if df.empty:
        return df
    if filters.fecha_desde is not None:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_publicacion"] >= ts]
    if filters.fecha_hasta is not None:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_publicacion"] <= ts]
    if filters.ccaa:
        df = df[df["ccaa"] == filters.ccaa]
    return df


def _explode_classified(df: pd.DataFrame) -> pd.DataFrame:
    """Explode comma-separated technologies and attach a readable label.

    Returns only rows with a non-empty technology, with a ``tech_label`` column.
    """
    out = df.copy()
    out["tecnologia"] = out["tecnologia"].fillna("").astype(str)
    out["tecnologia"] = out["tecnologia"].str.split(",")
    out = out.explode("tecnologia", ignore_index=True)
    out["tecnologia"] = out["tecnologia"].str.strip()
    out = out[out["tecnologia"] != ""]
    if out.empty:
        return out
    out["tech_label"] = out["tecnologia"].map(tecnologia_label)
    return out


def _sin_clasificar(df: pd.DataFrame) -> int:
    mask = df["tecnologia"].isna() | (df["tecnologia"].astype(str).str.strip() == "")
    return int(mask.sum())


def _build_entries(classified: pd.DataFrame, total: int) -> list[TecnologiaEntry]:
    grp = classified.groupby("tech_label")
    agg = grp.agg(count=("id_externo", "count"), importe=("importe", "sum"))
    if "estado" in classified.columns:
        # % adjudicado por tech = media del booleano (estado == ADJ) * 100.
        # Vectorizado (groupby de una Series) en vez de .apply para tipado limpio.
        is_adj = classified["estado"] == _ADJ_ESTADO
        adj = is_adj.groupby(classified["tech_label"]).mean().mul(100.0)
    else:
        adj = pd.Series(0.0, index=agg.index)
    agg = agg.join(adj.rename("pct_adjudicado")).sort_values("count", ascending=False).reset_index()
    return [
        TecnologiaEntry(
            tecnologia=row["tech_label"],
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
            importe_medio=float(row["importe"] or 0) / int(row["count"]) if row["count"] else 0.0,
            pct=round(int(row["count"]) / total * 100, 2) if total else 0.0,
            pct_adjudicado=round(float(row["pct_adjudicado"] or 0), 1),
        )
        for _, row in agg.iterrows()
    ]


def _top_labels(classified: pd.DataFrame, n: int) -> list[str]:
    return classified.groupby("tech_label")["id_externo"].count().nlargest(n).index.tolist()


def _build_cross_organo(classified: pd.DataFrame) -> list[CrossOrganoEntry]:
    if classified.empty or "organo_contratacion" not in classified.columns:
        return []
    sub = classified.dropna(subset=["organo_contratacion"])
    if sub.empty:
        return []
    top_orgs = sub.groupby("organo_contratacion")["id_externo"].count().nlargest(_TOP_ORGANOS).index
    top_techs = _top_labels(sub, _TOP_TECHS_CROSS)
    sub = sub[sub["organo_contratacion"].isin(top_orgs) & sub["tech_label"].isin(top_techs)]
    g = (
        sub.groupby(["organo_contratacion", "tech_label"])["id_externo"]
        .count()
        .reset_index(name="count")
    )
    return [
        CrossOrganoEntry(
            organo=str(row["organo_contratacion"]),
            tecnologia=str(row["tech_label"]),
            count=int(row["count"]),
        )
        for _, row in g.iterrows()
    ]


def _build_cross_geo(classified: pd.DataFrame) -> list[CrossGeoEntry]:
    if classified.empty or "ccaa" not in classified.columns:
        return []
    sub = classified.dropna(subset=["ccaa"])
    if sub.empty:
        return []
    top_ccaa = sub.groupby("ccaa")["id_externo"].count().nlargest(_TOP_CCAA).index
    top_techs = _top_labels(sub, _TOP_TECHS_EVOL)
    sub = sub[sub["ccaa"].isin(top_ccaa) & sub["tech_label"].isin(top_techs)]
    g = sub.groupby(["ccaa", "tech_label"])["id_externo"].count().reset_index(name="count")
    return [
        CrossGeoEntry(
            ccaa=str(row["ccaa"]), tecnologia=str(row["tech_label"]), count=int(row["count"])
        )
        for _, row in g.iterrows()
    ]


def _build_evolucion(classified: pd.DataFrame) -> list[EvolucionEntry]:
    if classified.empty or "fecha_publicacion" not in classified.columns:
        return []
    ts = classified.dropna(subset=["fecha_publicacion"]).copy()
    if ts.empty:
        return []
    top_techs = set(_top_labels(ts, _TOP_TECHS_EVOL))
    ts["tech_grp"] = ts["tech_label"].where(ts["tech_label"].isin(top_techs), _OTRAS)
    ts["mes"] = ts["fecha_publicacion"].dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    g = (
        ts.groupby(["mes", "tech_grp"])
        .agg(count=("id_externo", "count"), importe=("importe", "sum"))
        .reset_index()
        .sort_values("mes")
    )
    return [
        EvolucionEntry(
            mes=row["mes"].strftime("%Y-%m"),
            tecnologia=str(row["tech_grp"]),
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
        )
        for _, row in g.iterrows()
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_tecnologias(filters: TecnologiasFilters) -> TecnologiasResult:
    """Compute technology distribution, KPIs and cross-dimensional breakdowns."""
    log.info("analytics_tecnologias_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    if df.empty:
        log.info("analytics_tecnologias_done", total=0)
        return TecnologiasResult()

    total = len(df)
    sin_clasificar = _sin_clasificar(df)
    classified = _explode_classified(df)

    if classified.empty:
        return TecnologiasResult(sin_clasificar=sin_clasificar)

    entries = _build_entries(classified, total)

    # KPIs for the technology distribution view
    n_tecnologias = len(entries)
    lider = max(entries, key=lambda e: e.count) if entries else None
    importe_medio_global = (
        float(sum(e.importe for e in entries) / n_tecnologias) if n_tecnologias else 0.0
    )
    tasa_adjudicacion_media = (
        float(sum(e.pct_adjudicado for e in entries) / n_tecnologias) if n_tecnologias else 0.0
    )

    result = TecnologiasResult(
        tecnologias=entries,
        sin_clasificar=sin_clasificar,
        n_tecnologias=n_tecnologias,
        tecnologia_lider=lider.tecnologia if lider else None,
        lider_count=lider.count if lider else 0,
        importe_medio_global=round(importe_medio_global, 2),
        tasa_adjudicacion_media=round(tasa_adjudicacion_media, 1),
        cross_organo=_build_cross_organo(classified),
        cross_geo=_build_cross_geo(classified),
        evolucion_mensual=_build_evolucion(classified),
    )
    log.info(
        "analytics_tecnologias_done",
        total=n_tecnologias,
        sin_clasificar=sin_clasificar,
    )
    return result


def get_tecnologia_detalle(
    tecnologia: str, filters: TecnologiaDetalleFilters
) -> TecnologiaDetalleResult:
    """Top-N tenders for a single technology label, plus subset KPIs."""
    log.info("analytics_tecnologia_detalle_start", tecnologia=tecnologia)
    df = _load_df()
    df = _apply_filters(df, filters)
    if df.empty:
        return TecnologiaDetalleResult(tecnologia=tecnologia)

    classified = _explode_classified(df)
    if classified.empty:
        return TecnologiaDetalleResult(tecnologia=tecnologia)

    sub = classified[classified["tech_label"] == tecnologia]
    if sub.empty:
        return TecnologiaDetalleResult(tecnologia=tecnologia)

    # Drop the explode duplicates for accurate per-tender stats.
    sub = sub.drop_duplicates(subset=["id_externo"])
    n = len(sub)
    importe_total = float(sub["importe"].sum(skipna=True))
    importe_medio = float(sub["importe"].mean(skipna=True) or 0)

    top = sub.sort_values("importe", ascending=False).head(filters.limit)
    items = [
        TecnologiaDetalleItem(
            id_externo=str(row.get("id_externo", "")),
            titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
            organo_contratacion=(
                row.get("organo_contratacion") if pd.notna(row.get("organo_contratacion")) else None
            ),
            importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
            estado=estado_label(row.get("estado")) if pd.notna(row.get("estado")) else None,
            ccaa=row.get("ccaa") if pd.notna(row.get("ccaa")) else None,
            fecha_publicacion=(
                row["fecha_publicacion"].strftime("%Y-%m-%d")
                if pd.notna(row.get("fecha_publicacion"))
                else None
            ),
        )
        for _, row in top.iterrows()
    ]

    log.info("analytics_tecnologia_detalle_done", tecnologia=tecnologia, n=n)
    return TecnologiaDetalleResult(
        tecnologia=tecnologia,
        n=n,
        importe_total=importe_total,
        importe_medio=importe_medio,
        items=items,
    )
