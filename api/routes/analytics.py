"""Analytics endpoints — exposes aggregated data for the web frontend.

These endpoints provide the analytical layer that the web frontend
consumes via server-side JSON responses.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from api.routes.auth import get_current_session_user
from observability.logging import get_logger
from services.analytics.clusters import ClustersFilters, ClustersResult, get_clusters
from services.analytics.compare import CompareFilters, CompareResult, get_compare_periods
from services.analytics.competitors import CompetitorFilters, CompetitorResult, get_competitors
from services.analytics.forecast_svc import (
    ForecastFilters,
    ForecastVolumeResult,
    RetenderingFilters,
    RetenderingResult,
    get_forecast_volume,
    get_retendering_forecast,
)
from services.analytics.geography import GeoFilters, GeoResult, get_geography
from services.analytics.organo_detail import (
    OrganoDetailFilters,
    OrganoDetailResult,
    get_organo_detail,
)
from services.analytics.organos import OrganosFilters, OrganosResult, get_organos
from services.analytics.overview import OverviewFilters, OverviewResult, get_overview
from services.analytics.pipeline import PipelineFilters, PipelineResult, get_pipeline
from services.analytics.proyectos_modulos import (
    ProyectosModulosFilters,
    ProyectosModulosResult,
    get_proyectos_modulos,
)
from services.analytics.quality import QualityResult, get_quality
from services.analytics.resumen import (
    ResumenHoyFilters,
    ResumenHoyResult,
    ResumenNovedadesResult,
    SankeyFilters,
    SankeyResult,
    TimelineScatterFilters,
    TimelineScatterResult,
    TopLicitacionesFilters,
    TopLicitacionesResult,
    get_resumen_hoy,
    get_resumen_novedades,
    get_sankey_flow,
    get_timeline_scatter,
    get_top_licitaciones,
)
from services.analytics.scoring import ScoringFilters, ScoringResult, get_scoring
from services.analytics.tecnologias import (
    TecnologiaDetalleFilters,
    TecnologiaDetalleResult,
    TecnologiasFilters,
    TecnologiasResult,
    get_tecnologia_detalle,
    get_tecnologias,
)
from services.analytics.trends import TrendsFilters, TrendsResult, get_trends
from services.analytics.trends_cpv import TrendsCpvFilters, TrendsCpvResult, get_trends_cpv
from services.analytics.utes import UTEFilters, UTEResult, get_utes
from services.source_health import SourceFreshnessResult, get_source_freshness
from shared.cache import cache_response

log = get_logger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewResult)
@cache_response(ttl=300, user_scoped=False)
def overview(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    estado: str | None = Query(default=None, description="Filter by estado"),
    q: str | None = Query(default=None, description="Free-text search (titulo, organo, id)"),
    importe_min: float | None = Query(default=None, ge=0, description="Min tender budget (EUR)"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> OverviewResult:
    """Return aggregated KPIs, breakdowns, and funnel data."""
    filters = OverviewFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        estado=estado,
        q=q,
        importe_min=importe_min,
    )
    return get_overview(filters)


@router.get("/trends", response_model=TrendsResult)
@cache_response(ttl=300, user_scoped=False)
def trends(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    group_by: Literal["month", "week", "day"] = Query(
        default="month", description="Group by month, week or day"
    ),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> TrendsResult:
    """Time series trends with heatmap and YoY deltas."""
    filters = TrendsFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        group_by=group_by,
    )
    return get_trends(filters)


@router.get("/geography", response_model=GeoResult)
@cache_response(ttl=300, user_scoped=False)
def geography(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> GeoResult:
    """Geographic distribution by CCAA."""
    filters = GeoFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tecnologia=tecnologia,
    )
    return get_geography(filters)


@router.get("/competitors", response_model=CompetitorResult)
@cache_response(ttl=300, cpu_bound=True, user_scoped=False)
def competitors(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by technology"),
    estado: str | None = Query(default=None, description="Filter by tender status"),
    importe_min: float | None = Query(default=None, ge=0, description="Min tender budget (EUR)"),
    limit: int = Query(default=20, ge=1, le=100, description="Max competitors to return"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> CompetitorResult:
    """Competitor analysis — market share, HHI, bidder rankings."""
    filters = CompetitorFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        estado=estado,
        importe_min=importe_min,
        limit=limit,
    )
    return get_competitors(filters)


# El modo page-aligned puntúa una página del listado; el listado nunca pide más
# de 500 filas y `limit` ya está acotado ahí. Sin este tope, un CSV arbitrario
# se traducía en un `IN (...)` con tantos placeholders como ids llegaran y en un
# bucle de pandas sin cota — el mismo trabajo no acotado que tumbaba la API
# antes de recortar el universo puntuable.
_MAX_SCORING_IDS = 500


def _parse_scoring_ids(ids: str | None) -> list[str] | None:
    """CSV de ids → lista, o 422 si excede la cota."""
    if not ids:
        return None
    id_list = [i for i in ids.split(",") if i]
    if len(id_list) > _MAX_SCORING_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"ids admite como maximo {_MAX_SCORING_IDS} elementos, llegaron {len(id_list)}",
        )
    return id_list


@router.get("/scoring", response_model=ScoringResult)
@cache_response(ttl=300, cpu_bound=True)
def scoring(
    min_score: int = Query(default=0, ge=0, le=100, description="Minimum score threshold"),
    limit: int = Query(default=50, ge=1, le=500, description="Max opportunities to return"),
    band: str | None = Query(
        default=None, description="Filter by band (Caliente|Atractiva|Tibia|Descarte)"
    ),
    tecnologia: str | None = Query(
        default=None,
        description="Filter by tecnologia (se aplica al universo, antes del top-N)",
    ),
    ids: str | None = Query(
        default=None,
        description=(
            "CSV de id_externo (maximo 500): puntua exactamente esas licitaciones "
            "(alineado a la pagina del listado), ignorando min_score/band/limit/tecnologia"
        ),
    ),
    exclude_dismissed: bool = Query(
        default=False,
        description=(
            "Excluye del ranking las senales que el usuario descarto, antes de "
            "ordenar y cortar. Se ignora en modo ids."
        ),
    ),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> ScoringResult:
    """Opportunity scoring — ranked by commercial potential, or page-aligned by ids.

    Cuando el usuario tiene un perfil (Feature B), aplica sus pesos y keywords
    personalizados. Sin perfil, usa los settings globales.

    En modo top-N el universo son las oportunidades vivas (estado no terminal y
    plazo por vencer); ``tecnologia`` lo acota antes de ordenar y cortar, para
    que el top-N sea el de esa tecnología y no el global filtrado después.
    """
    user_key = str(_user.get("user_key") or "") or None
    id_list = _parse_scoring_ids(ids)
    filters = ScoringFilters(
        min_score=min_score,
        limit=limit,
        band=band,
        tecnologia=tecnologia,
        ids=id_list,
        exclude_dismissed=exclude_dismissed,
    )
    return get_scoring(filters, user_key=user_key)


@router.get("/quality", response_model=QualityResult)
@cache_response(ttl=600, user_scoped=False)
def quality(
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> QualityResult:
    """Data quality metrics — completeness and scrape freshness."""
    return get_quality()


@router.get(
    "/source-freshness",
    response_model=SourceFreshnessResult,
    summary="Frescura y SLA por fuente de ingesta",
)
def source_freshness(
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> SourceFreshnessResult:
    """Hace visibles cursores atascados, runs fallidos y detección <24h."""
    return get_source_freshness()


@router.get("/organos", response_model=OrganosResult)
@cache_response(ttl=300, cpu_bound=True, user_scoped=False)
def organos(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    q: str | None = Query(
        default=None,
        max_length=200,
        description="Search organo name (accent/case-insensitive substring)",
    ),
    limit: int = Query(default=50, ge=1, le=500, description="Max organos to return"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> OrganosResult:
    """Ranking of contracting bodies by activity."""
    filters = OrganosFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        q=q,
        limit=limit,
    )
    return get_organos(filters)


@router.get("/tecnologias", response_model=TecnologiasResult)
@cache_response(ttl=300, user_scoped=False)
def tecnologias(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> TecnologiasResult:
    """Technology distribution across licitaciones."""
    filters = TecnologiasFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
    )
    return get_tecnologias(filters)


@router.get("/tecnologias/detail", response_model=TecnologiaDetalleResult)
@cache_response(ttl=300, user_scoped=False)
def tecnologias_detail(
    tecnologia: str = Query(description="Technology label to filter by"),
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    limit: int = Query(default=100, ge=1, le=500, description="Max tenders to return"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> TecnologiaDetalleResult:
    """Top-N tenders for a single technology, with subset KPIs."""
    filters = TecnologiaDetalleFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        limit=limit,
    )
    return get_tecnologia_detalle(tecnologia, filters)


@router.get("/proyectos-modulos", response_model=ProyectosModulosResult)
@cache_response(ttl=300, user_scoped=False)
def proyectos_modulos(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> ProyectosModulosResult:
    """SAP module and project type breakdown."""
    filters = ProyectosModulosFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        tecnologia=tecnologia,
    )
    return get_proyectos_modulos(filters)


@router.get("/clusters", response_model=ClustersResult)
@cache_response(ttl=1800, cpu_bound=True, user_scoped=False)
def clusters(
    n_clusters: int | None = Query(default=None, ge=2, le=20, description="Desired cluster count"),
    auto_k: bool = Query(default=False, description="Auto-select k via silhouette score"),
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> ClustersResult:
    """Semantic clustering of tenders (KMeans over TF-IDF) with keyword labels."""
    filters = ClustersFilters(
        n_clusters=n_clusters,
        auto_k=auto_k,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
    )
    return get_clusters(filters)


@router.get("/pipeline", response_model=PipelineResult)
@cache_response(ttl=120, cpu_bound=True, user_scoped=False)
def pipeline(
    dias: int = Query(default=30, ge=1, le=365, description="Deadline window in days"),
    limit: int = Query(default=50, ge=1, le=500, description="Max entries to return"),
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    estado: str | None = Query(default=None, description="Filter by estado"),
    q: str | None = Query(default=None, description="Free-text search (titulo, organo, id)"),
    importe_min: float | None = Query(default=None, ge=0, description="Min tender budget (EUR)"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> PipelineResult:
    """Upcoming deadlines and urgency alerts."""
    filters = PipelineFilters(
        dias=dias,
        limit=limit,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        estado=estado,
        q=q,
        importe_min=importe_min,
    )
    return get_pipeline(filters)


@router.get("/resumen/novedades", response_model=ResumenNovedadesResult)
@cache_response(ttl=120)
def resumen_novedades(
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> ResumenNovedadesResult:
    """New licitaciones since user's last visit."""
    return get_resumen_novedades(_user["user_id"])


@router.get("/resumen/hoy", response_model=ResumenHoyResult)
@cache_response(ttl=120, user_scoped=False)
def resumen_hoy(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> ResumenHoyResult:
    """Para hoy — calientes, vencimientos, nuevas."""
    filters = ResumenHoyFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
    )
    return get_resumen_hoy(filters)


@router.get("/resumen/timeline", response_model=TimelineScatterResult)
@cache_response(ttl=300, user_scoped=False)
def resumen_timeline(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> TimelineScatterResult:
    """Scatter data for timeline visualization."""
    filters = TimelineScatterFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
    )
    return get_timeline_scatter(filters)


@router.get("/resumen/sankey", response_model=SankeyResult)
@cache_response(ttl=300, user_scoped=False)
def resumen_sankey(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> SankeyResult:
    """Sankey flow: tipo_contrato → estado."""
    filters = SankeyFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
    )
    return get_sankey_flow(filters)


@router.get("/resumen/top", response_model=TopLicitacionesResult)
@cache_response(ttl=300, user_scoped=False)
def resumen_top(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    n: int = Query(default=10, ge=1, le=100, description="Number of top licitaciones"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> TopLicitacionesResult:
    """Top N licitaciones by importe."""
    filters = TopLicitacionesFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        n=n,
    )
    return get_top_licitaciones(filters)


@router.get("/forecast/volume", response_model=ForecastVolumeResult)
@cache_response(ttl=600, cpu_bound=True, user_scoped=False)
def forecast_volume_endpoint(
    months_ahead: int = Query(default=6, ge=1, le=24, description="Months to forecast"),
    metric: str = Query(default="count", description="Metric: count or sum"),
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> ForecastVolumeResult:
    """Volume forecast using Holt-Winters / linear regression."""
    filters = ForecastFilters(
        months_ahead=months_ahead,
        metric=metric,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
    )
    return get_forecast_volume(filters)


@router.get(
    "/forecast/retendering",
    response_model=RetenderingResult,
    deprecated=True,
)
@cache_response(ttl=600, cpu_bound=True, user_scoped=False)
def forecast_retendering(
    meses_anticipacion: int = Query(default=6, ge=1, le=24, description="Months anticipation"),
    solo_mantenimiento: bool = Query(default=True, description="Only maintenance contracts"),
    horizonte_dias: int = Query(default=365, ge=1, le=1825, description="Horizon in days"),
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> RetenderingResult:
    """Retendering forecast — contracts approaching end of term.

    .. deprecated:: 2026-07-20
       Sin consumidor en `web/` desde el rework de Pipeline & Alertas — el
       mismo ángulo ("contratos que vencen próximamente") lo cubre
       ``GET /competitive/renovaciones`` con un dataset más rico (incluye
       `riesgo_cambio` y opportunity score). Se mantiene el endpoint por
       compatibilidad de contrato público (retirarlo es breaking change,
       AGENTS.md §5) hasta confirmar ausencia de consumidores externos.
       Ver docs/IMPROVEMENT_BACKLOG.md (Cerrados, 2026-07-20).
    """
    filters = RetenderingFilters(
        meses_anticipacion=meses_anticipacion,
        solo_mantenimiento=solo_mantenimiento,
        horizonte_dias=horizonte_dias,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
    )
    return get_retendering_forecast(filters)


@router.get("/trends-cpv", response_model=TrendsCpvResult)
@cache_response(ttl=300, user_scoped=False)
def trends_cpv(
    cpv: str | None = Query(default=None, description="Specific CPV to focus"),
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    top_n: int = Query(default=15, ge=1, le=50, description="Top N CPVs"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> TrendsCpvResult:
    """Per-CPV time series and rankings."""
    filters = TrendsCpvFilters(
        cpv=cpv,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        top_n=top_n,
    )
    return get_trends_cpv(filters)


@router.get("/organos/{organo}", response_model=OrganoDetailResult)
@cache_response(ttl=300, cpu_bound=True, user_scoped=False)
def organo_detail(
    organo: str,
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> OrganoDetailResult:
    """Drill-down for a single contracting body."""
    filters = OrganoDetailFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
    )
    return get_organo_detail(organo, filters)


@router.get("/utes", response_model=UTEResult)
@cache_response(ttl=300, user_scoped=False)
def utes(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> UTEResult:
    """UTE-specific analysis from adjudicaciones."""
    filters = UTEFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
    )
    return get_utes(filters)


@router.get("/compare-periods", response_model=CompareResult)
@cache_response(ttl=300, user_scoped=False)
def compare_periods(
    range_a_desde: date = Query(description="Period A start date"),
    range_a_hasta: date = Query(description="Period A end date"),
    range_b_desde: date = Query(description="Period B start date"),
    range_b_hasta: date = Query(description="Period B end date"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> CompareResult:
    """Compare two time periods side-by-side."""
    filters = CompareFilters(
        range_a_desde=range_a_desde,
        range_a_hasta=range_a_hasta,
        range_b_desde=range_b_desde,
        range_b_hasta=range_b_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
    )
    return get_compare_periods(filters)
