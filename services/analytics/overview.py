"""Analytics overview service for aggregated tender KPIs and breakdowns.

Las agregaciones (KPIs, breakdowns por estado/mes/organo, indicadores de
mercado) se calculan en Postgres vía ``db.repositories.aggregates`` — antes se
cargaba la tabla ``licitaciones`` completa (~47k filas) a pandas y se
agregaba en el proceso web (capado a 4 hilos, ver ``api/app.py`` y el
postmortem de ``services/_data_cache.py``). Postgres resuelve estos
``GROUP BY`` en milisegundos.

``hhi``/``pct_oferta_unica``/``lead_time_medio`` se agregan también en
Postgres (``overview_adjudicaciones_indicadores``) — antes venían del
DataFrame full-table de ``load_adjudicaciones()`` (27 s y ~170k filas por
llamada medidos en prod), que en Render además estaba bloqueado por
``render_api_full_table_loads_blocked`` y dejaba los tres KPIs a cero/None.
Siguen ignorando los filtros del endpoint, como siempre hicieron.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AggregateRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OverviewFilters(BaseModel):
    """Query filters for the overview endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    q: str | None = None
    importe_min: float | None = None


class EstadoCount(BaseModel):
    """Count per estado."""

    estado: str
    n: int


class MesAggregate(BaseModel):
    """Monthly aggregate."""

    mes: str
    n_licitaciones: int
    importe: float


class OrganoAggregate(BaseModel):
    """Top organo aggregate."""

    organo_contratacion: str
    n: int
    importe: float


class FunnelStep(BaseModel):
    """Funnel step with absolute count and percentage."""

    estado: str
    n: int
    pct: float


class OverviewResult(BaseModel):
    """Combined overview response."""

    total_licitaciones: int = 0
    importe_total: float = 0.0
    importe_medio: float = 0.0
    organos_unicos: int = 0
    yoy_delta: float = 0.0
    licitaciones_30d: int = 0
    importe_30d: float = 0.0
    por_estado: list[EstadoCount] = Field(default_factory=list)
    por_mes: list[MesAggregate] = Field(default_factory=list)
    top_organos: list[OrganoAggregate] = Field(default_factory=list)
    funnel_estados: list[FunnelStep] = Field(default_factory=list)
    hhi: float = 0.0
    pct_oferta_unica: float = 0.0
    # Market indicators
    pct_pyme: float = 0.0
    concentracion_top10: float = 0.0
    lead_time_medio: float | None = None
    tasa_anulacion: float = 0.0
    concentracion_geo_top3: float = 0.0
    ccaa_cubiertas: int = 0
    # "Para hoy" counts
    calientes_hoy: int = 0
    vencen_48h: int = 0
    nuevas_24h: int = 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_repo_filters(filters: OverviewFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
        estado=filters.estado,
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        importe_min=filters.importe_min,
        q=filters.q,
    )


def _adj_indicadores() -> dict[str, float | None]:
    """HHI, % oferta única, lead time medio y % PYME — en Postgres, sin filtros."""
    try:
        return _repo.overview_adjudicaciones_indicadores()
    except Exception:
        log.warning("overview_adj_indicadores_failed", exc_info=True)
        return {
            "hhi": 0.0,
            "pct_oferta_unica": 0.0,
            "lead_time_medio": None,
            "pct_pyme": 0.0,
        }


def get_overview(filters: OverviewFilters) -> OverviewResult:
    """Compute the full overview payload — agregaciones vía SQL en Postgres."""
    log.info("analytics_overview_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)
    adj_ind = _adj_indicadores()

    k = _repo.overview_kpis(repo_filters)

    hoy = datetime.now(UTC)
    hace_30d_iso = (hoy - timedelta(days=30)).isoformat()
    hace_60d_iso = (hoy - timedelta(days=60)).isoformat()
    hace_365d_iso = (hoy - timedelta(days=365)).isoformat()
    hace_24h_iso = (hoy - timedelta(hours=24)).isoformat()
    hoy_iso = hoy.isoformat()
    limite_48h_iso = (hoy + timedelta(hours=48)).isoformat()

    yoy_data = _repo.overview_yoy_and_recent(
        repo_filters, hace_30d_iso=hace_30d_iso, hace_60d_iso=hace_60d_iso
    )
    v_act = yoy_data["lics_30d"]
    v_prev = yoy_data["lics_prev30d"]
    yoy = ((v_act - v_prev) / v_prev * 100) if v_prev else 0.0

    # --- Market indicators ---
    top10_imp, total_imp = _repo.overview_concentracion_organos(repo_filters, top_n=10)
    total_imp = total_imp or 1.0
    concentracion_top10 = top10_imp / total_imp * 100

    anul_count, total_12m = _repo.overview_tasa_anulacion(repo_filters, hace_365d_iso=hace_365d_iso)
    tasa_anulacion = (anul_count / total_12m * 100) if total_12m > 0 else 0.0

    top3_imp, total_imp_geo = _repo.overview_concentracion_ccaa(repo_filters, top_n=3)
    total_imp_geo = total_imp_geo or 1.0
    concentracion_geo_top3 = top3_imp / total_imp_geo * 100

    ccaa_cubiertas = _repo.overview_ccaa_cubiertas(repo_filters)

    para_hoy = _repo.overview_para_hoy(
        repo_filters,
        hoy_iso=hoy_iso,
        limite_48h_iso=limite_48h_iso,
        hace_24h_iso=hace_24h_iso,
    )

    por_estado = [
        EstadoCount(estado=row["estado"], n=int(row["n"]))
        for row in _repo.overview_por_estado(repo_filters)
    ]
    por_mes = [
        MesAggregate(
            mes=row["mes"], n_licitaciones=int(row["n_licitaciones"]), importe=float(row["importe"])
        )
        for row in _repo.overview_por_mes(repo_filters)
    ]
    top_organos = [
        OrganoAggregate(
            organo_contratacion=row["organo_contratacion"],
            n=int(row["n"]),
            importe=float(row["importe"]),
        )
        for row in _repo.overview_top_organos(repo_filters)
    ]

    funnel_data = _repo.overview_funnel(repo_filters)
    total_funnel = funnel_data["total"]
    funnel_estados = [
        FunnelStep(
            estado=est,
            n=funnel_data[est],
            pct=float(funnel_data[est] / total_funnel * 100) if total_funnel else 0.0,
        )
        for est in ("PUB", "EV", "RES", "ADJ", "ANUL")
    ]

    result = OverviewResult(
        total_licitaciones=k["total"],
        importe_total=k["importe_total"],
        importe_medio=k["importe_medio"],
        organos_unicos=k["organos"],
        yoy_delta=yoy,
        licitaciones_30d=int(v_act),
        importe_30d=yoy_data["importe_30d"],
        por_estado=por_estado,
        por_mes=por_mes,
        top_organos=top_organos,
        funnel_estados=funnel_estados,
        hhi=adj_ind["hhi"] or 0.0,
        pct_oferta_unica=adj_ind["pct_oferta_unica"] or 0.0,
        pct_pyme=adj_ind["pct_pyme"] or 0.0,
        concentracion_top10=concentracion_top10,
        lead_time_medio=adj_ind["lead_time_medio"],
        tasa_anulacion=tasa_anulacion,
        concentracion_geo_top3=concentracion_geo_top3,
        ccaa_cubiertas=ccaa_cubiertas,
        calientes_hoy=para_hoy["calientes_hoy"],
        vencen_48h=para_hoy["vencen_48h"],
        nuevas_24h=para_hoy["nuevas_24h"],
    )
    log.info("analytics_overview_done", total=result.total_licitaciones)
    return result
