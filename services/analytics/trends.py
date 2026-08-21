"""Trends analytics — monthly/weekly evolution, heatmap data, forecast.

Agrega en Postgres vía :class:`AggregateRepository` (ADR-023): la serie se
construye sobre el GROUP BY diario (cientos de filas post-agregación) y el
roll-up a semana/mes se hace en Python. Hasta 2026-08 este módulo cargaba la
tabla completa a pandas en el proceso API — bloqueado en Render por el
cortacircuitos full-table, que dejaba el endpoint vacío en producción.

**Cota del tamaño de la respuesta.** ``series`` no escala con el número de
licitaciones sino con la LONGITUD DEL RANGO DE FECHAS, así que un ``limit`` por
filas —el idioma de paginación del resto del API— es aquí la herramienta
equivocada: no hay "página siguiente" de una serie temporal. Los dos mandos
correctos son la granularidad del roll-up (``group_by``, expuesto al cliente) y
el rango; este módulo aplica además un techo duro de :data:`MAX_TREND_POINTS`
puntos para que la respuesta no pueda crecer sin cota conforme se acumule
histórico.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AggregateRepository()

TrendsFreq = Literal["month", "week", "day"]

#: Techo duro de puntos de ``series``. Está deliberadamente por encima del rango
#: más ancho que puede pedir un consumidor actual —el Calendario pide
#: ``group_by=day`` sin fechas, o sea todo el histórico diario, y 4.000 puntos
#: son ~11 años— para que la respuesta de hoy sea idéntica byte a byte. Existe
#: para que el contrato tenga cota: a partir de ahí la serie se recorta al tramo
#: MÁS RECIENTE y la respuesta lo declara en ``serie_truncada``, en vez de
#: engordar indefinidamente. Recortar (y no re-agregar a una granularidad más
#: gruesa) es deliberado: el Calendario filtra los periodos por
#: ``^\\d{4}-\\d{2}-\\d{2}$`` y devolverle semanas sería un calendario vacío.
MAX_TREND_POINTS = 4000


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TrendsFilters(BaseModel):
    """Query filters for trends."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    group_by: TrendsFreq = Field(
        default="month",
        description=(
            "Frecuencia del roll-up de la serie temporal. Es el mando que acota "
            "el tamaño de `series`: la serie crece con la LONGITUD DEL RANGO DE "
            "FECHAS, no con el número de licitaciones, así que pedir menos filas "
            "no sirve de nada. A `day` sale ~1 punto por día (10 años ≈ 3.650 "
            "puntos); `week` da ~1/7 de eso y `month` ~1/30. Para rangos largos, "
            "engorda la granularidad en vez de recortar el rango. El default "
            "`month` es el de siempre."
        ),
    )


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
    group_by: TrendsFreq = Field(
        default="month",
        description=(
            "Granularidad del roll-up con la que se construyó `series` "
            "(el `group_by` pedido). El formato de `period` depende de ella: "
            "`YYYY-MM` en month, `YYYY-Www` (p. ej. 2026-W10) en week y "
            "`YYYY-MM-DD` en day."
        ),
    )
    serie_truncada: bool = Field(
        default=False,
        description=(
            f"True si `series` alcanzó el techo de {MAX_TREND_POINTS} puntos y se "
            "recortó al tramo más reciente. Para cubrir un rango más largo sin "
            "perder tramo, pide una granularidad más gruesa en `group_by`. "
            "`waterfall` se calcula sobre la serie ya recortada; `heatmap`, "
            "`histogram_bins` y `mes_pico` siguen midiendo el rango completo."
        ),
    )


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


def _clip_series(series: list[TrendPoint]) -> tuple[list[TrendPoint], bool]:
    """Acota la serie a :data:`MAX_TREND_POINTS`, conservando el tramo reciente.

    ``trends_daily`` devuelve los días con ``ORDER BY dia`` y ``_build_series``
    preserva ese orden, así que la cola de la lista es el tramo más reciente —
    que es el que un gráfico de tendencia necesita si hay que sacrificar algo.
    """
    if len(series) <= MAX_TREND_POINTS:
        return series, False
    return series[-MAX_TREND_POINTS:], True


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
    series, serie_truncada = _clip_series(_build_series(daily, filters.group_by))
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
        group_by=filters.group_by,
        serie_truncada=serie_truncada,
    )
    log.info(
        "analytics_trends_done",
        points=len(result.series),
        group_by=filters.group_by,
        truncada=serie_truncada,
    )
    return result
