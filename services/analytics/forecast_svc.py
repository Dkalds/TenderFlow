"""Forecast analytics — volume forecasting and retendering predictions.

ADR-023: el forecast de volumen consume la serie mensual YA agregada en
Postgres (``forecast_monthly`` → ``forecast_volume_from_monthly``) y el de
re-licitación una proyección ACOTADA (solo filas con duración positiva o
``fecha_fin`` explícita — las únicas que pueden producir una fecha de fin).
Hasta 2026-08 ambos cargaban las dos tablas completas al proceso API —
bloqueado en Render por el cortacircuitos full-table, que dejaba los
endpoints vacíos en producción.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.analytics.forecast import (
    BANDA_SIGMAS,
    build_forecast_df,
    forecast_volume_from_monthly,
)

log = get_logger(__name__)

_repo = AggregateRepository()


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
    # Qué motor produjo la proyección ("holt-winters" | "regresion-lineal"). La
    # caída al fallback lineal solo se veía en el log, y la pantalla presentaba
    # ambas igual: quien lee la curva no sabía si miraba un suavizado estacional
    # o una recta. `None` cuando no hay serie.
    modelo: str | None = None
    # Sigmas de la banda `lower`/`upper`. NO es un intervalo de confianza: es
    # +/-N sigma de TODA la serie histórica, idéntico en los seis horizontes (un IC
    # real se ensancha con el horizonte). Se publica para que la UI la rotule
    # con el número real en vez de dejar que se lea como un IC.
    banda_sigmas: float = BANDA_SIGMAS


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


def _to_repo_filters(filters: Any) -> LicitacionesFilters:
    fecha_desde = getattr(filters, "fecha_desde", None)
    fecha_hasta = getattr(filters, "fecha_hasta", None)
    return LicitacionesFilters(
        fecha_desde=fecha_desde.isoformat() if fecha_desde else None,
        fecha_hasta=fecha_hasta.isoformat() if fecha_hasta else None,
        ccaa=getattr(filters, "ccaa", None),
        tecnologia=getattr(filters, "tecnologia", None),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_forecast_volume(filters: ForecastFilters) -> ForecastVolumeResult:
    """Forecast licitaciones volume using Holt-Winters / linear fallback."""
    log.info("analytics_forecast_volume_start", filters=filters.model_dump(exclude_none=True))
    monthly = _repo.forecast_monthly(_to_repo_filters(filters), metric=filters.metric)
    if not monthly:
        return ForecastVolumeResult()

    hist = pd.DataFrame(
        {
            "mes": [pd.Timestamp(str(r["mes"]) + "-01") for r in monthly],
            "valor": [float(r["valor"] or 0) for r in monthly],
        }
    )
    result_df = forecast_volume_from_monthly(hist, months_ahead=filters.months_ahead)
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

    # `modelo` es constante en todo el DataFrame (lo fija el motor que produjo
    # la proyección), así que basta con leerlo de la primera fila.
    modelo = str(result_df["modelo"].iloc[0]) if "modelo" in result_df.columns else None

    log.info("analytics_forecast_volume_done", points=len(series), modelo=modelo)
    return ForecastVolumeResult(series=series, modelo=modelo)


def get_retendering_forecast(filters: RetenderingFilters) -> RetenderingResult:
    """Retendering forecast using build_forecast_df logic.

    .. deprecated:: 2026-07-20
       Sin consumidor en `web/` desde el rework de Pipeline & Alertas — ver
       nota de deprecación en ``api/routes/analytics.py::forecast_retendering``
       y docs/IMPROVEMENT_BACKLOG.md (Cerrados, 2026-07-20).
    """
    log.info("analytics_retendering_start", filters=filters.model_dump(exclude_none=True))
    rows = _repo.retendering_universe(_to_repo_filters(filters))
    if not rows:
        return RetenderingResult()

    df = pd.DataFrame(rows)
    df = df.assign(
        importe=pd.to_numeric(df["importe"], errors="coerce"),
        duracion_valor=pd.to_numeric(df["duracion_valor"], errors="coerce"),
    )
    titulo_lower = df["titulo"].fillna("").str.lower()
    df["tipo_proyecto"] = "Otro"
    df.loc[titulo_lower.str.contains("mantenimiento|soporte", na=False), "tipo_proyecto"] = (
        "Mantenimiento"
    )

    adj_rows = _repo.adjudicaciones_para_forecast(
        [str(i) for i in df["id_externo"].astype(str).tolist()]
    )
    adj_df = pd.DataFrame(adj_rows)
    if not adj_df.empty:
        adj_df = adj_df.assign(
            fecha_adjudicacion=pd.to_datetime(adj_df["fecha_adjudicacion"], errors="coerce"),
            importe_adjudicado=pd.to_numeric(adj_df["importe_adjudicado"], errors="coerce"),
            n_ofertas_recibidas=pd.to_numeric(adj_df["n_ofertas_recibidas"], errors="coerce"),
        )

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
