"""Analytics endpoints — exposes aggregated data for the dashboard.

These endpoints provide the analytical layer that the Streamlit dashboard
previously computed in-memory. Now computed server-side and served as JSON.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from api.routes.auth import get_current_session_user
from observability.logging import get_logger
from services.analytics.competitors import CompetitorFilters, CompetitorResult, get_competitors
from services.analytics.geography import GeoFilters, GeoResult, get_geography
from services.analytics.organos import OrganosFilters, OrganosResult, get_organos
from services.analytics.overview import OverviewFilters, OverviewResult, get_overview
from services.analytics.pipeline import PipelineFilters, PipelineResult, get_pipeline
from services.analytics.proyectos_modulos import (
    ProyectosModulosFilters,
    ProyectosModulosResult,
    get_proyectos_modulos,
)
from services.analytics.quality import QualityResult, get_quality
from services.analytics.scoring import ScoringFilters, ScoringResult, get_scoring
from services.analytics.tecnologias import TecnologiasFilters, TecnologiasResult, get_tecnologias
from services.analytics.trends import TrendsFilters, TrendsResult, get_trends

log = get_logger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/overview", response_model=OverviewResult)
def overview(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    estado: str | None = Query(default=None, description="Filter by estado"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> OverviewResult:
    """Return aggregated KPIs, breakdowns, and funnel data."""
    filters = OverviewFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        estado=estado,
    )
    return get_overview(filters)


@router.get("/trends", response_model=TrendsResult)
def trends(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    group_by: Literal["month", "week"] = Query(
        default="month", description="Group by month or week"
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
def competitors(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    limit: int = Query(default=20, ge=1, le=100, description="Max competitors to return"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> CompetitorResult:
    """Competitor analysis — market share, HHI, bidder rankings."""
    filters = CompetitorFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        limit=limit,
    )
    return get_competitors(filters)


@router.get("/scoring", response_model=ScoringResult)
def scoring(
    min_score: int = Query(default=0, ge=0, le=100, description="Minimum score threshold"),
    limit: int = Query(default=50, ge=1, le=500, description="Max opportunities to return"),
    band: str | None = Query(default=None, description="Filter by band (alta|media|baja)"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> ScoringResult:
    """Opportunity scoring — ranked by commercial potential."""
    filters = ScoringFilters(
        min_score=min_score,
        limit=limit,
        band=band,
    )
    return get_scoring(filters)


@router.get("/quality", response_model=QualityResult)
def quality(
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> QualityResult:
    """Data quality metrics — completeness and scrape freshness."""
    return get_quality()


@router.get("/organos", response_model=OrganosResult)
def organos(
    fecha_desde: date | None = Query(default=None, description="Start date (YYYY-MM-DD)"),
    fecha_hasta: date | None = Query(default=None, description="End date (YYYY-MM-DD)"),
    ccaa: str | None = Query(default=None, description="Filter by CCAA"),
    tecnologia: str | None = Query(default=None, description="Filter by tecnologia"),
    limit: int = Query(default=50, ge=1, le=500, description="Max organos to return"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> OrganosResult:
    """Ranking of contracting bodies by activity."""
    filters = OrganosFilters(
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        ccaa=ccaa,
        tecnologia=tecnologia,
        limit=limit,
    )
    return get_organos(filters)


@router.get("/tecnologias", response_model=TecnologiasResult)
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


@router.get("/proyectos-modulos", response_model=ProyectosModulosResult)
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


@router.get("/pipeline", response_model=PipelineResult)
def pipeline(
    dias: int = Query(default=30, ge=1, le=365, description="Deadline window in days"),
    limit: int = Query(default=50, ge=1, le=500, description="Max entries to return"),
    _user: dict[str, Any] = Depends(get_current_session_user),
) -> PipelineResult:
    """Upcoming deadlines and urgency alerts."""
    filters = PipelineFilters(dias=dias, limit=limit)
    return get_pipeline(filters)
