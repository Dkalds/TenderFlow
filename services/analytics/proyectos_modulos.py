"""Proyectos & Modulos analytics — SAP module and project type breakdown.

Agrega en Postgres vía :class:`AggregateRepository` (ADR-023): la detección de
módulos SAP se evalúa en el motor (``titulo ~* patrón``) con las mismas
alternancias escapadas que compilaba este módulo con ``re.IGNORECASE``. La
proyección de stats nunca tuvo columna ``descripcion``, así que la detección
sigue siendo sobre ``titulo`` — sin cambio de señal. Hasta 2026-08 cargaba la
tabla completa a pandas en el proceso API (vacío en producción por el
cortacircuitos full-table de Render).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field

from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.classification import cpv_label, estado_label

log = get_logger(__name__)

_repo = AggregateRepository()

# Sentinel used by the frontend to render "NUEVO" instead of a percentage.
_YOY_NUEVO = 999.0
_TOP_CPV = 15


# ---------------------------------------------------------------------------
# SAP module detection keywords
# ---------------------------------------------------------------------------

_SAP_MODULES: dict[str, list[str]] = {
    "S/4HANA": ["s/4hana", "s4hana", "s/4 hana"],
    "HANA": ["hana", "sap hana"],
    "FI": ["sap fi", "financiero", "finanzas sap", " fi "],
    "CO": ["sap co", "controlling", " co "],
    "MM": ["sap mm", "gestión de materiales", "materials management", " mm "],
    "SD": ["sap sd", "ventas y distribución", "sales and distribution", " sd "],
    "PP": ["sap pp", "planificación de producción", " pp "],
    "PM": ["sap pm", "mantenimiento de planta", "plant maintenance"],
    "HR": ["sap hr", "recursos humanos sap"],
    "HCM": ["sap hcm", "human capital", "gestión del capital humano"],
    "BW": ["sap bw", "business warehouse", "sap bi"],
    "Ariba": ["ariba", "sap ariba"],
    "SuccessFactors": ["successfactors", "success factors"],
    "EWM": ["sap ewm", "extended warehouse"],
    "CRM": ["sap crm", "customer relationship"],
    "SRM": ["sap srm", "supplier relationship"],
    "GTS": ["sap gts", "global trade"],
    "IS-U": ["is-u", "sap utilities"],
    "FICO": ["fico", "sap fico"],
    "BASIS": ["sap basis", "netweaver", "administración sap"],
}

# Patrones regex (alternancias escapadas) que el repositorio evalúa con `~*`.
_MODULE_SQL_PATTERNS: dict[str, str] = {
    mod: "|".join(re.escape(kw) for kw in keywords) for mod, keywords in _SAP_MODULES.items()
}
_ALL_MODULES_PATTERN = "|".join(
    re.escape(kw) for keywords in _SAP_MODULES.values() for kw in keywords
)

# Versión compilada de los mismos patrones: referencia de paridad con el SQL
# (los tests la ejercitan) y utilidad puntual para clasificar un texto suelto.
_MODULE_PATTERNS: dict[str, re.Pattern[str]] = {
    mod: re.compile(pattern, re.IGNORECASE) for mod, pattern in _MODULE_SQL_PATTERNS.items()
}


def _detect_modules(text: str) -> list[str]:
    """Detect SAP modules mentioned in a text string (paridad con `~*` en SQL)."""
    if not text:
        return []
    return [mod for mod, pattern in _MODULE_PATTERNS.items() if pattern.search(text)]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class ProyectosModulosFilters(BaseModel):
    """Query filters for proyectos-modulos endpoint."""

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    tecnologia: str | None = None


class ModuloEntry(BaseModel):
    """Single SAP module entry."""

    modulo: str
    count: int
    importe: float


class ProyectoTipoEntry(BaseModel):
    """Single project type entry."""

    tipo: str
    count: int
    importe: float


class TopModuloYoY(BaseModel):
    """Fastest-growing SAP module year-over-year."""

    modulo: str
    crecimiento_pct: float
    n_act: int


class TipoEstadoEntry(BaseModel):
    """tipo_contrato x estado cell (for the stacked-bar relationship)."""

    tipo: str
    estado: str
    n: int


class CpvEntry(BaseModel):
    """Top CPV code aggregate."""

    cpv: str
    cpv_desc: str
    count: int
    importe: float


class ProyectosModulosResult(BaseModel):
    """Combined proyectos & modulos response."""

    modulos: list[ModuloEntry] = Field(default_factory=list)
    tipos_proyecto: list[ProyectoTipoEntry] = Field(default_factory=list)
    total_clasificados: int = 0
    # KPIs a nivel licitación (distinct): NO suma de filas de módulo. Una licitación
    # con módulos A+B cuenta una sola vez → sin doble conteo de importe/ticket.
    importe_total_sap: float = 0.0
    ticket_medio_sap: float = 0.0
    top_modulo_yoy: TopModuloYoY | None = None
    tipo_estado: list[TipoEstadoEntry] = Field(default_factory=list)
    cpv: list[CpvEntry] = Field(default_factory=list)


def _to_repo_filters(filters: ProyectosModulosFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        tecnologia=filters.tecnologia,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _top_modulo_yoy(repo_filters: LicitacionesFilters) -> TopModuloYoY | None:
    """Fastest-growing module: last 12 months vs the previous 12 months."""
    hoy = datetime.now(UTC)
    windows = _repo.proyectos_modulos_yoy(
        repo_filters,
        module_patterns=_MODULE_SQL_PATTERNS,
        hace_365d_iso=(hoy - timedelta(days=365)).isoformat(),
        hace_730d_iso=(hoy - timedelta(days=730)).isoformat(),
    )
    act = {mod: n_act for mod, (n_act, _n_prev) in windows.items() if n_act > 0}
    if not act:
        return None

    # Reduce noise: prefer modules with at least 2 mentions this year.
    candidates = {m: n for m, n in act.items() if n >= 2} or act

    best_mod: str | None = None
    best_growth = -1e18
    best_n = 0
    for mod, n_act in candidates.items():
        n_prev = windows[mod][1]
        growth = _YOY_NUEVO if n_prev == 0 else (n_act - n_prev) / n_prev * 100
        if growth > best_growth or (growth == best_growth and n_act > best_n):
            best_growth, best_mod, best_n = growth, mod, n_act

    if best_mod is None:
        return None
    return TopModuloYoY(
        modulo=best_mod,
        crecimiento_pct=round(float(best_growth), 1),
        n_act=int(best_n),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_proyectos_modulos(filters: ProyectosModulosFilters) -> ProyectosModulosResult:
    """Compute SAP module and project type breakdown."""
    log.info("analytics_proyectos_modulos_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)

    por_modulo, total_clasificados, importe_total_sap = _repo.proyectos_modulos_stats(
        repo_filters,
        module_patterns=_MODULE_SQL_PATTERNS,
        all_pattern=_ALL_MODULES_PATTERN,
    )
    modulos = sorted(
        (
            ModuloEntry(modulo=mod, count=count, importe=importe)
            for mod, (count, importe) in por_modulo.items()
        ),
        key=lambda e: e.count,
        reverse=True,
    )

    tipos_proyecto = [
        ProyectoTipoEntry(
            tipo=str(r["tipo_contrato"]),
            count=int(r["count"]),
            importe=float(r["importe"] or 0),
        )
        for r in _repo.tipos_contrato_breakdown(repo_filters)
    ]
    ticket_medio_sap = importe_total_sap / total_clasificados if total_clasificados else 0.0

    tipo_estado = [
        TipoEstadoEntry(
            tipo=str(r["tipo_contrato"]),
            estado=estado_label(r["estado"]),
            n=int(r["n"]),
        )
        for r in _repo.tipo_estado_crosstab(repo_filters)
    ]
    cpv = [
        CpvEntry(
            cpv=str(r["cpv"]),
            cpv_desc=cpv_label(str(r["cpv"])),
            count=int(r["count"]),
            importe=float(r["importe"] or 0),
        )
        for r in _repo.cpv_top_por_count(repo_filters, n=_TOP_CPV)
    ]

    result = ProyectosModulosResult(
        modulos=modulos,
        tipos_proyecto=tipos_proyecto,
        total_clasificados=total_clasificados,
        importe_total_sap=round(importe_total_sap, 2),
        ticket_medio_sap=round(ticket_medio_sap, 2),
        top_modulo_yoy=_top_modulo_yoy(repo_filters),
        tipo_estado=tipo_estado,
        cpv=cpv,
    )
    log.info(
        "analytics_proyectos_modulos_done",
        modulos=len(result.modulos),
        tipos=len(result.tipos_proyecto),
        cpv=len(result.cpv),
    )
    return result
