"""Trends analytics — monthly/weekly evolution, heatmap data, forecast.

Agrega en Postgres vía :class:`AggregateRepository` (ADR-023): la serie se
construye sobre el GROUP BY diario (cientos de filas post-agregación) y el
roll-up a semana/mes se hace en Python. Hasta 2026-08 este módulo cargaba la
tabla completa a pandas en el proceso API — bloqueado en Render por el
cortacircuitos full-table, que dejaba el endpoint vacío en producción.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AggregateRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TrendsFilters(BaseModel):
    """Query filters for trends."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    group_by: Literal["month", "week", "day"] = "month"


class TrendPoint(BaseModel):
    """Single point in the time series."""

    period: str
    count: int
    importe: float


class HeatmapCell(BaseModel):
    """Single cell in the month x estado heatmap."""

    row: str
    col: str
    value: int


class WaterfallPoint(BaseModel):
    """Month-to-month delta."""

    period: str
    delta: int
    cumulative: int


class HistogramBin(BaseModel):
    """Importe distribution bin."""

    bin_label: str
    count: int


class TrendsResult(BaseModel):
    """Combined trends response."""

    series: list[TrendPoint] = Field(default_factory=list)
    heatmap: list[HeatmapCell] = Field(default_factory=list)
    yoy_count: float = 0.0
    yoy_importe: float = 0.0
    waterfall: list[WaterfallPoint] = Field(default_factory=list)
    histogram_bins: list[HistogramBin] = Field(default_factory=list)
    mes_pico: dict[str, Any] | None = None


def _to_repo_filters(filters: TrendsFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
    )


# ---------------------------------------------------------------------------
# Internal helpers (roll-up en Python sobre el GROUP BY diario)
# ---------------------------------------------------------------------------


def _period_label(dia: str, freq: str) -> str | None:
    """Etiqueta de periodo para un día ISO; ``None`` si el día no es parseable.

    Réplica del formato pandas original: mes ``%Y-%m``, día ``%Y-%m-%d`` y
    semana ``%Y-W%V`` calculada sobre el lunes de la semana (el timestamp de
    inicio del periodo semanal de pandas).
    """
    if freq == "month":
        return dia[:7]
    if freq == "day":
        return dia[:10]
    try:
        d = date.fromisoformat(dia[:10])
    except ValueError:
        return None
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y-W%V")


def _build_series(daily: list[dict[str, Any]], freq: str) -> list[TrendPoint]:
    buckets: dict[str, list[float]] = {}
    for row in daily:
        label = _period_label(str(row["dia"]), freq)
        if label is None:
            continue
        agg = buckets.setdefault(label, [0, 0.0])
        agg[0] += int(row["count"])
        agg[1] += float(row["importe"] or 0)
    return [
        TrendPoint(period=label, count=int(c), importe=imp) for label, (c, imp) in buckets.items()
    ]


def _yoy_from_repo(filters: LicitacionesFilters) -> tuple[float, float]:
    hoy = datetime.now(UTC)
    vals = _repo.trends_yoy(
        filters,
        hace_365d_iso=(hoy - timedelta(days=365)).isoformat(),
        hace_730d_iso=(hoy - timedelta(days=730)).isoformat(),
    )
    cnt_cur, cnt_prev = vals["cnt_cur"], vals["cnt_prev"]
    imp_cur, imp_prev = vals["imp_cur"], vals["imp_prev"]
    yoy_count = ((cnt_cur - cnt_prev) / cnt_prev * 100) if cnt_prev else 0.0
    yoy_importe = ((imp_cur - imp_prev) / imp_prev * 100) if imp_prev else 0.0
    return yoy_count, yoy_importe


def _build_waterfall(series: list[TrendPoint]) -> list[WaterfallPoint]:
    """Build waterfall (month-to-month delta) from series."""
    if not series:
        return []
    result: list[WaterfallPoint] = []
    cumulative = 0
    prev_count = 0
    for i, pt in enumerate(series):
        delta = pt.count - prev_count if i > 0 else pt.count
        cumulative += delta
        result.append(WaterfallPoint(period=pt.period, delta=delta, cumulative=cumulative))
        prev_count = pt.count
    return result


def _find_mes_pico(daily: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Mes con mayor importe total (primer máximo en caso de empate)."""
    monthly: dict[str, list[float]] = {}
    for row in daily:
        mes = str(row["dia"])[:7]
        agg = monthly.setdefault(mes, [0, 0.0])
        agg[0] += int(row["count"])
        agg[1] += float(row["importe"] or 0)
    if not monthly:
        return None
    best_mes, best = max(monthly.items(), key=lambda kv: kv[1][1])
    return {"mes": best_mes, "importe": best[1], "count": int(best[0])}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_trends(filters: TrendsFilters) -> TrendsResult:
    """Compute time-series trends, heatmap, and YoY deltas."""
    log.info("analytics_trends_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)

    daily = _repo.trends_daily(repo_filters)
    series = _build_series(daily, filters.group_by)
    heatmap = [
        HeatmapCell(row=str(r["mes"]), col=str(r["estado"]), value=int(r["value"]))
        for r in _repo.trends_heatmap(repo_filters)
    ]
    yoy_count, yoy_importe = _yoy_from_repo(repo_filters)

    result = TrendsResult(
        series=series,
        heatmap=heatmap,
        yoy_count=yoy_count,
        yoy_importe=yoy_importe,
        waterfall=_build_waterfall(series),
        histogram_bins=[
            HistogramBin(bin_label=label, count=count)
            for label, count in _repo.trends_histogram(repo_filters)
        ],
        mes_pico=_find_mes_pico(daily),
    )
    log.info("analytics_trends_done", points=len(result.series))
    return result
