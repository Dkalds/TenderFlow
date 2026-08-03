"""Pipeline analytics — upcoming deadlines and alerts.

ADR-023: la ventana de vencimientos se trae como proyección ACOTADA desde
Postgres (``AggregateRepository.pipeline_window`` — solo las filas con
``fecha_limite`` dentro de la ventana pedida, con los filtros en el WHERE) y
los buckets/scoring posteriores operan en pandas sobre ese resultado ya
pequeño. Hasta 2026-08 este módulo cargaba la tabla completa al proceso API —
bloqueado en Render por el cortacircuitos full-table, que dejaba el endpoint
vacío en producción. El contexto de percentiles del scoring viene de SQL
(``importe_percentiles``), no de materializar la tabla.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.analytics.scoring import score_dataframe

log = get_logger(__name__)

_repo = AggregateRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class PipelineFilters(BaseModel):
    """Query filters for pipeline endpoint."""

    dias: int = 30
    limit: int = 50
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    q: str | None = None
    importe_min: float | None = None


class PipelineEntry(BaseModel):
    """Single pipeline entry with deadline info."""

    id_externo: str
    titulo: str | None = None
    organo_contratacion: str | None = None
    importe: float | None = None
    fecha_limite: str | None = None
    dias_restantes: int
    estado: str | None = None
    score: int | None = None
    band: str | None = None


class HorizonteCount(BaseModel):
    """Count by horizon bucket."""

    horizonte: str
    count: int
    importe: float


class TrimestreCount(BaseModel):
    """Count by calendar quarter."""

    trimestre: str
    count: int
    importe: float


class UrgenciaValorPoint(BaseModel):
    """Scatter point: urgency vs value."""

    id_externo: str
    titulo: str | None = None
    dias_restantes: int
    importe: float
    es_urgente: bool


class PipelineResult(BaseModel):
    """Combined pipeline response."""

    upcoming: list[PipelineEntry] = Field(default_factory=list)
    total_en_plazo: int = 0
    vencen_7d: int = 0
    vencen_30d: int = 0
    # Dimensión económica del pipeline (suma de importe sobre el dataset completo
    # de la ventana, no solo los `limit` items devueltos). Antes el frontend no
    # tenía forma de mostrar "cuánto € hay en juego" sin re-derivarlo.
    valor_total: float = 0.0
    valor_7d: float = 0.0
    valor_30d: float = 0.0
    # Oportunidades con score de banda "Caliente" (≥75) dentro de la ventana
    # completa, no solo los `limit` items devueltos.
    calientes: int = 0
    valor_calientes: float = 0.0
    # Sin consumidor en `web/` desde el rework de Pipeline & Alertas
    # (2026-07-20, ver docs/IMPROVEMENT_BACKLOG.md Cerrados): el rework
    # sustituyó los charts "Distribución por horizonte"/"Volumen trimestral"
    # por el banner de /renovaciones. Se mantienen en el DTO porque retirar
    # un campo del contrato público es un cambio breaking (AGENTS.md §5) —
    # no se retira sin RFC/confirmación humana.
    por_horizonte: list[HorizonteCount] = Field(default_factory=list)
    por_trimestre: list[TrimestreCount] = Field(default_factory=list)
    urgencia_valor: list[UrgenciaValorPoint] = Field(default_factory=list)


def _to_repo_filters(filters: PipelineFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
        estado=filters.estado,
        importe_min=filters.importe_min,
        q=filters.q,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_pipeline(filters: PipelineFilters) -> PipelineResult:
    """Compute upcoming deadlines and urgency alerts."""
    log.info("analytics_pipeline_start", dias=filters.dias, limit=filters.limit)
    hoy = datetime.now(UTC)
    rows = _repo.pipeline_window(
        _to_repo_filters(filters),
        hoy_iso=hoy.isoformat(),
        # (fecha_limite - hoy).days <= dias  ⟺  fecha_limite < hoy + (dias+1)d
        hasta_iso=(hoy + timedelta(days=filters.dias + 1)).isoformat(),
    )
    if not rows:
        log.info("analytics_pipeline_done", total=0)
        return PipelineResult()

    all_df = pd.DataFrame(rows)
    all_df = all_df.assign(
        fecha_limite_dt=pd.to_datetime(all_df["fecha_limite"], errors="coerce", utc=True),
        importe=pd.to_numeric(all_df["importe"], errors="coerce"),
    )
    all_df = all_df.dropna(subset=["fecha_limite_dt"])
    hoy_ts = pd.Timestamp(hoy)
    all_df = all_df[all_df["fecha_limite_dt"] > hoy_ts]
    if all_df.empty:
        log.info("analytics_pipeline_done", total=0)
        return PipelineResult()
    all_df = all_df.copy()
    all_df["dias_restantes"] = (all_df["fecha_limite_dt"] - hoy_ts).dt.days
    all_df = all_df[all_df["dias_restantes"] <= filters.dias]
    if all_df.empty:
        log.info("analytics_pipeline_done", total=0)
        return PipelineResult()

    total_en_plazo = len(all_df)
    vencen_7d = int((all_df["dias_restantes"] <= 7).sum())
    vencen_30d = int((all_df["dias_restantes"] <= 30).sum())
    valor_total = float(all_df["importe"].sum(skipna=True))
    valor_7d = float(all_df.loc[all_df["dias_restantes"] <= 7, "importe"].sum(skipna=True))
    valor_30d = float(all_df.loc[all_df["dias_restantes"] <= 30, "importe"].sum(skipna=True))

    # Score de toda la ventana (no solo los `limit` devueltos). Contexto:
    # percentiles P10/P90 globales desde SQL; la afinidad es por-fila, así que
    # calcularla sobre la ventana equivale a calcularla sobre la tabla entera
    # y consultar estos ids.
    score_df = score_dataframe(all_df, all_df, importe_percentiles=_repo.importe_percentiles())
    if not score_df.empty:
        all_df["id_externo"] = all_df["id_externo"].astype(str)
        all_df = all_df.merge(score_df, on="id_externo", how="left")
    else:
        all_df["score"] = None
        all_df["band"] = None

    calientes_mask = all_df["band"] == "Caliente"
    calientes = int(calientes_mask.sum())
    valor_calientes = float(
        pd.to_numeric(all_df.loc[calientes_mask, "importe"], errors="coerce").sum(skipna=True)
    )

    df = all_df.sort_values("dias_restantes").head(filters.limit)

    upcoming = []
    for _, row in df.iterrows():
        upcoming.append(
            PipelineEntry(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                organo_contratacion=(
                    row.get("organo_contratacion")
                    if pd.notna(row.get("organo_contratacion"))
                    else None
                ),
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                fecha_limite=str(row.get("fecha_limite", "")) or None,
                dias_restantes=int(row["dias_restantes"]),
                estado=row.get("estado") if pd.notna(row.get("estado")) else None,
                score=int(row["score"]) if pd.notna(row.get("score")) else None,
                band=row.get("band") if pd.notna(row.get("band")) else None,
            )
        )

    # por_horizonte: [0,7), [7,30), [30,90), [90,∞)
    por_horizonte: list[HorizonteCount] = []
    bins = [0, 7, 30, 90, float("inf")]
    labels = ["<7d", "7-30d", "30-90d", "90+d"]
    all_df["_horizonte"] = pd.cut(all_df["dias_restantes"], bins=bins, labels=labels, right=False)
    for label in labels:
        subset = all_df[all_df["_horizonte"] == label]
        por_horizonte.append(
            HorizonteCount(
                horizonte=label,
                count=len(subset),
                importe=float(subset["importe"].sum(skipna=True)),
            )
        )

    # por_trimestre: group by quarter of fecha_limite
    por_trimestre: list[TrimestreCount] = []
    all_df["_quarter"] = all_df["fecha_limite_dt"].dt.to_period("Q")
    q_grp = (
        all_df.dropna(subset=["_quarter"])
        .groupby("_quarter")
        .agg(_count=("id_externo", "count"), _importe=("importe", "sum"))
        .reset_index()
        .sort_values("_quarter")
    )
    for _, row in q_grp.iterrows():
        por_trimestre.append(
            TrimestreCount(
                trimestre=str(row["_quarter"]),
                count=int(row["_count"]),
                importe=float(row["_importe"] or 0),
            )
        )

    # urgencia_valor: scatter (dias_restantes vs importe), max 200
    urgencia_valor: list[UrgenciaValorPoint] = []
    uv_df = all_df.dropna(subset=["importe"]).head(200)
    for _, row in uv_df.iterrows():
        urgencia_valor.append(
            UrgenciaValorPoint(
                id_externo=str(row.get("id_externo", "")),
                titulo=row.get("titulo") if pd.notna(row.get("titulo")) else None,
                dias_restantes=int(row["dias_restantes"]),
                importe=float(row["importe"]),
                es_urgente=int(row["dias_restantes"]) <= 7,
            )
        )

    result = PipelineResult(
        upcoming=upcoming,
        total_en_plazo=total_en_plazo,
        vencen_7d=vencen_7d,
        vencen_30d=vencen_30d,
        valor_total=valor_total,
        valor_7d=valor_7d,
        valor_30d=valor_30d,
        calientes=calientes,
        valor_calientes=valor_calientes,
        por_horizonte=por_horizonte,
        por_trimestre=por_trimestre,
        urgencia_valor=urgencia_valor,
    )
    log.info(
        "analytics_pipeline_done",
        total=total_en_plazo,
        vencen_7d=vencen_7d,
        calientes=calientes,
    )
    return result
