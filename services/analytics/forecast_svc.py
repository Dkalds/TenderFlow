"""Forecast analytics — volume forecasting and retendering predictions."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.adjudicaciones import load_raw_adjudicaciones
from services.analytics.forecast import build_forecast_df, forecast_volume
from services.licitaciones import load_stats_base_df

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ForecastFilters(BaseModel):
    months_ahead: int = 6
    metric: str = "count"
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class ForecastSeriesPoint(BaseModel):
    mes: str
    valor: float
    tipo: str
    lower: float | None = None
    upper: float | None = None


class ForecastVolumeResult(BaseModel):
    series: list[ForecastSeriesPoint] = Field(default_factory=list)


class RetenderingFilters(BaseModel):
    meses_anticipacion: int = 6
    solo_mantenimiento: bool = True
    horizonte_dias: int = 365
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None


class ForecastEntry(BaseModel):
    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    fecha_fin_estimada: str | None = None
    dias_hasta_fin: int | None = None
    estado_forecast: str | None = None
    adjudicatarios: str | None = None
    baja_pct: float | None = None


class RetenderingResumen(BaseModel):
    ya_vencido: int = 0
    menos_3m: int = 0
    tres_seis_m: int = 0
    seis_doce_m: int = 0
    mas_doce_m: int = 0


class RetenderingResult(BaseModel):
    forecast_entries: list[ForecastEntry] = Field(default_factory=list)
    resumen: RetenderingResumen = Field(default_factory=RetenderingResumen)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_licit_df() -> pd.DataFrame:
    df = load_stats_base_df()
    if not df.empty:
        df["fecha_publicacion"] = pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True)
        fi_col = df.get("fecha_inicio")
        if fi_col is not None:
            df["fecha_inicio"] = pd.to_datetime(fi_col, errors="coerce")
        ff_col = df.get("fecha_fin")
        if ff_col is not None:
            df["fecha_fin"] = pd.to_datetime(ff_col, errors="coerce")
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
        df["duracion_valor"] = pd.to_numeric(
            df.get("duracion_valor", pd.Series(dtype=float)), errors="coerce"
        )
        if "duracion_unidad" not in df.columns:
            df["duracion_unidad"] = None
        # tipo_proyecto enrichment
        titulo_lower = df.get("titulo", pd.Series(dtype=str)).fillna("").str.lower()
        df["tipo_proyecto"] = "Otro"
        maint_mask = titulo_lower.str.contains("mantenimiento|soporte", na=False)
        df.loc[maint_mask, "tipo_proyecto"] = "Mantenimiento"
    return df


def _load_adj_df() -> pd.DataFrame:
    rows = load_raw_adjudicaciones()
    df = pd.DataFrame(rows)
    if not df.empty:
        if "fecha_adjudicacion" in df.columns:
            df["fecha_adjudicacion"] = pd.to_datetime(
                df["fecha_adjudicacion"], errors="coerce", utc=True
            )
        for col in ("importe_adjudicado", "n_ofertas_recibidas"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "nombre" not in df.columns and "adjudicatario" in df.columns:
            df["nombre"] = df["adjudicatario"]
        if "licitacion_id" not in df.columns and "id_externo" in df.columns:
            df["licitacion_id"] = df["id_externo"]
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
    if getattr(filters, "ccaa", None) and "ccaa" in df.columns:
        df = df[df["ccaa"] == filters.ccaa]
    if getattr(filters, "tecnologia", None) and "tecnologia" in df.columns:
        df = df[df["tecnologia"] == filters.tecnologia]
    return df


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_forecast_volume(filters: ForecastFilters) -> ForecastVolumeResult:
    """Forecast licitaciones volume using Holt-Winters / linear fallback."""
    log.info("analytics_forecast_volume_start", filters=filters.model_dump(exclude_none=True))
    df = _load_licit_df()
    df = _apply_filters(df, filters)

    if df.empty:
        return ForecastVolumeResult()

    result_df = forecast_volume(df, months_ahead=filters.months_ahead, metric=filters.metric)
    if result_df.empty:
        return ForecastVolumeResult()

    series = [
        ForecastSeriesPoint(
            mes=row["mes"].strftime("%Y-%m") if pd.notna(row["mes"]) else "",
            valor=float(row["valor"]) if pd.notna(row.get("valor")) else 0.0,
            tipo=str(row.get("tipo", "")),
            lower=float(row["lower"]) if pd.notna(row.get("lower")) else None,
            upper=float(row["upper"]) if pd.notna(row.get("upper")) else None,
        )
        for _, row in result_df.iterrows()
    ]

    log.info("analytics_forecast_volume_done", points=len(series))
    return ForecastVolumeResult(series=series)


def get_retendering_forecast(filters: RetenderingFilters) -> RetenderingResult:
    """Retendering forecast using build_forecast_df logic."""
    log.info("analytics_retendering_start", filters=filters.model_dump(exclude_none=True))
    df = _load_licit_df()
    df = _apply_filters(df, filters)
    adj_df = _load_adj_df()

    if df.empty:
        return RetenderingResult()

    forecast_df = build_forecast_df(
        df,
        adj_df,
        meses_anticipacion=filters.meses_anticipacion,
        solo_mantenimiento=filters.solo_mantenimiento,
    )

    if forecast_df.empty:
        return RetenderingResult()

    # Filter by horizonte_dias
    horizonte = filters.horizonte_dias
    forecast_df = forecast_df[
        forecast_df["dias_hasta_fin"].notna() & (forecast_df["dias_hasta_fin"] <= horizonte)
    ]

    # Build resumen
    estado_counts = forecast_df["estado_forecast"].value_counts()
    resumen = RetenderingResumen(
        ya_vencido=int(estado_counts.get("Ya vencido", 0)),
        menos_3m=int(estado_counts.get("<3 meses", 0)),
        tres_seis_m=int(estado_counts.get("3-6 meses", 0)),
        seis_doce_m=int(estado_counts.get("6-12 meses", 0)),
        mas_doce_m=int(estado_counts.get(">12 meses", 0)),
    )

    entries = []
    for _, row in forecast_df.iterrows():
        entries.append(
            ForecastEntry(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                organo_contratacion=(
                    row.get("organo_contratacion")
                    if pd.notna(row.get("organo_contratacion"))
                    else None
                ),
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                fecha_fin_estimada=(
                    row["fecha_fin_estimada"].isoformat()
                    if pd.notna(row.get("fecha_fin_estimada"))
                    else None
                ),
                dias_hasta_fin=(
                    int(row["dias_hasta_fin"]) if pd.notna(row.get("dias_hasta_fin")) else None
                ),
                estado_forecast=(
                    str(row["estado_forecast"]) if pd.notna(row.get("estado_forecast")) else None
                ),
                adjudicatarios=(
                    str(row["adjudicatarios"]) if pd.notna(row.get("adjudicatarios")) else None
                ),
                baja_pct=(float(row["baja_pct"]) if pd.notna(row.get("baja_pct")) else None),
            )
        )

    log.info("analytics_retendering_done", entries=len(entries))
    return RetenderingResult(forecast_entries=entries, resumen=resumen)
