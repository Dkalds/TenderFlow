"""Proyectos y módulos — qué se licita, por familia tecnológica, y SAP por módulo.

Hasta 2026-10 la vista solo entendía módulos SAP. Ahora agrupa por las
**familias** de la taxonomía (``config.keywords.FAMILIAS_TECNOLOGICAS``: ERP,
CRM, cloud e infraestructura, ciberseguridad, datos e IA…), cada una con su
categoría y los fabricantes de su línea, y los módulos SAP quedan como
desglose dentro de ERP: se detectan solo sobre lo etiquetado como SAP.

Agrega en Postgres vía :class:`AggregateRepository` (ADR-023): la pertenencia a
una familia es el solapamiento del CSV de ``tecnologia`` con sus códigos, y la
detección de módulos SAP se evalúa en el motor (``titulo ~* patrón``) con las
mismas alternancias escapadas que compilaba este módulo con ``re.IGNORECASE``.
La proyección de stats nunca tuvo columna ``descripcion``, así que la detección
sigue siendo sobre ``titulo`` — sin cambio de señal. Hasta 2026-08 cargaba la
tabla completa a pandas en el proceso API (vacío en producción por el
cortacircuitos full-table de Render).
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field

from config.keywords import (
    FAMILIA_DE_FABRICANTE,
    FAMILIAS_TECNOLOGICAS,
    TECH_CATEGORIAS,
    TECH_LABEL_TIPO,
    codigos_de_familia,
    etiqueta_familia,
)
from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.classification import cpv_label, estado_label

log = get_logger(__name__)

_repo = AggregateRepository()

# Sentinel used by the frontend to render "NUEVO" instead of a percentage.
_YOY_NUEVO = 999.0
_TOP_CPV = 15

#: Códigos de ``tecnologia`` de cada familia, en el orden de la taxonomía.
_CODIGOS_POR_FAMILIA: dict[str, list[str]] = {
    f: codigos_de_familia(f) for f in FAMILIAS_TECNOLOGICAS
}

#: Fabricantes transversales: no cuentan en ninguna familia (ver
#: ``config.keywords.FAMILIA_DE_FABRICANTE``) y la respuesta los nombra.
_FABRICANTES_SIN_FAMILIA: list[str] = sorted(
    TECH_CATEGORIAS[label]
    for label, tipo in TECH_LABEL_TIPO.items()
    if tipo == "fabricante" and label not in FAMILIA_DE_FABRICANTE
)

#: Dónde se buscan los módulos SAP: lo etiquetado como SAP, el desglose de ERP.
_CODIGOS_SAP = ["SAP"]


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


class FamiliaEntry(BaseModel):
    """Una familia de la taxonomía: cuántas licitaciones y cuánto importe."""

    familia: str
    etiqueta: str
    count: int
    importe: float
    #: ``importe / count``: lo que pesa de media una licitación de la familia.
    importe_medio: float


class TopFamiliaYoY(BaseModel):
    """La familia que más crece: últimos 12 meses frente a los 12 anteriores."""

    familia: str
    etiqueta: str
    crecimiento_pct: float
    n_act: int


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

    # ── Familias ──────────────────────────────────────────────────────────
    #: Las familias con alguna licitación, de más a menos licitaciones.
    familias: list[FamiliaEntry] = Field(default_factory=list)
    # Denominador del ámbito: TODAS las licitaciones que pasan los filtros, con
    # o sin familia. El frontend no puede reconstruirlo — sumar las filas de
    # `familias` cuenta dos veces una licitación de dos familias, el mismo
    # fallback que invertía el KPI de multi-módulo (a más multi-módulo, más bajo
    # leía). Se emite explícito para que la tarjeta pueda rotular «x / N».
    total: int = 0
    #: Licitaciones del ámbito con alguna familia, cada una una vez.
    total_con_familia: int = 0
    #: Suma de las filas de `familias`: una licitación de dos familias suma 2.
    #: Nunca es denominador de un porcentaje de licitaciones.
    menciones_familia: int = 0
    #: ``total_con_familia / total``, en %.
    pct_con_familia: float = 0.0
    #: ``menciones_familia / total_con_familia``: 1,0 = cada una de una familia.
    familias_por_licitacion: float = 0.0
    #: Importe de las licitaciones con familia, cada una una vez.
    importe_con_familia: float = 0.0
    ticket_medio_familia: float = 0.0
    top_familia_yoy: TopFamiliaYoY | None = None
    #: Fabricantes que venden en varias familias y por eso no cuentan en
    #: ninguna (etiqueta de UI): lo que la vista tiene que decir que no suma.
    fabricantes_sin_familia: list[str] = Field(default_factory=list)

    # ── Desglose de ERP: módulos SAP ──────────────────────────────────────
    #: Detectados solo sobre lo etiquetado como SAP.
    modulos: list[ModuloEntry] = Field(default_factory=list)
    #: Licitaciones SAP del ámbito: el denominador del desglose.
    total_sap: int = 0
    #: Licitaciones SAP con al menos un módulo detectado.
    total_clasificados: int = 0
    # Suma de detecciones por módulo: una licitación con A+B suma 2. NO es un
    # conteo de licitaciones, así que nunca es denominador de un porcentaje de
    # licitaciones; solo numerador de la densidad de módulos de abajo.
    menciones_modulo: int = 0
    # Los dos ratios del desglose, cada uno con SU denominador:
    #   pct_sap_con_modulo       = total_clasificados / total_sap
    #   modulos_por_clasificada  = menciones_modulo / total_clasificados
    # El segundo mide intensidad multi-módulo con el signo correcto: 1,0 = todas
    # mono-módulo, y sube al detectarse más módulos por licitación. El primero
    # dividía por el ámbito entero («Match portfolio») cuando la vista era solo
    # de SAP; en una vista de todas las familias divide por lo que es SAP.
    pct_sap_con_modulo: float = 0.0
    modulos_por_clasificada: float = 0.0
    # Deprecado: la pantalla lo cambió por `pct_sap_con_modulo`, pero el campo
    # sale en la respuesta hasta que lo retire una RFC (docs/api-design.md,
    # «Qué cuenta como cambio incompatible»). Misma definición de siempre.
    pct_match_portfolio: float = Field(
        default=0.0,
        deprecated=True,
        description=(
            "Deprecado: licitaciones con módulo SAP sobre el ámbito entero, en %. "
            "Usa `pct_sap_con_modulo`."
        ),
    )
    # KPIs a nivel licitación (distinct): NO suma de filas de módulo. Una licitación
    # con módulos A+B cuenta una sola vez → sin doble conteo de importe/ticket.
    importe_total_sap: float = 0.0
    ticket_medio_sap: float = 0.0
    top_modulo_yoy: TopModuloYoY | None = None

    # ── Tipos de contrato y CPV del ámbito ────────────────────────────────
    tipos_proyecto: list[ProyectoTipoEntry] = Field(default_factory=list)
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


def _ventanas_yoy() -> tuple[str, str]:
    """Inicio de los últimos 12 meses y de los 12 anteriores, en ISO."""
    hoy = datetime.now(UTC)
    return (hoy - timedelta(days=365)).isoformat(), (hoy - timedelta(days=730)).isoformat()


def _el_que_mas_crece(windows: dict[str, tuple[int, int]]) -> tuple[str, float, int] | None:
    """(clave, crecimiento %, n del último año) de la que más crece, o ``None``.

    Sin año anterior, el crecimiento es el centinela ``_YOY_NUEVO``. Prefiere
    las que tienen al menos dos este año: una sola mención que sale de cero
    ganaría siempre.
    """
    act = {clave: n_act for clave, (n_act, _n_prev) in windows.items() if n_act > 0}
    if not act:
        return None
    candidates = {clave: n for clave, n in act.items() if n >= 2} or act

    best: str | None = None
    best_growth = -1e18
    best_n = 0
    for clave, n_act in candidates.items():
        n_prev = windows[clave][1]
        growth = _YOY_NUEVO if n_prev == 0 else (n_act - n_prev) / n_prev * 100
        if growth > best_growth or (growth == best_growth and n_act > best_n):
            best_growth, best, best_n = growth, clave, n_act
    if best is None:
        return None
    return best, round(float(best_growth), 1), int(best_n)


def _top_modulo_yoy(repo_filters: LicitacionesFilters) -> TopModuloYoY | None:
    """El módulo SAP que más crece: últimos 12 meses frente a los 12 anteriores."""
    hace_365d, hace_730d = _ventanas_yoy()
    windows = _repo.proyectos_modulos_yoy(
        repo_filters,
        module_patterns=_MODULE_SQL_PATTERNS,
        hace_365d_iso=hace_365d,
        hace_730d_iso=hace_730d,
        solo_codigos=_CODIGOS_SAP,
    )
    top = _el_que_mas_crece(windows)
    if top is None:
        return None
    modulo, crecimiento, n_act = top
    return TopModuloYoY(modulo=modulo, crecimiento_pct=crecimiento, n_act=n_act)


def _top_familia_yoy(repo_filters: LicitacionesFilters) -> TopFamiliaYoY | None:
    """La familia que más crece: últimos 12 meses frente a los 12 anteriores."""
    hace_365d, hace_730d = _ventanas_yoy()
    windows = _repo.proyectos_familias_yoy(
        repo_filters,
        codigos_por_familia=_CODIGOS_POR_FAMILIA,
        hace_365d_iso=hace_365d,
        hace_730d_iso=hace_730d,
    )
    top = _el_que_mas_crece(windows)
    if top is None:
        return None
    familia, crecimiento, n_act = top
    return TopFamiliaYoY(
        familia=familia,
        etiqueta=etiqueta_familia(familia),
        crecimiento_pct=crecimiento,
        n_act=n_act,
    )


def _familias(repo_filters: LicitacionesFilters) -> tuple[list[FamiliaEntry], int, float]:
    """Las familias con alguna licitación + (con alguna familia, su importe)."""
    por_familia, con_familia, importe = _repo.proyectos_familias_stats(
        repo_filters, codigos_por_familia=_CODIGOS_POR_FAMILIA
    )
    familias = sorted(
        (
            FamiliaEntry(
                familia=familia,
                etiqueta=etiqueta_familia(familia),
                count=count,
                importe=importe_familia,
                importe_medio=round(importe_familia / count, 2),
            )
            for familia, (count, importe_familia) in por_familia.items()
        ),
        # A igual recuento, el orden de la taxonomía: estable entre llamadas.
        key=lambda e: (-e.count, FAMILIAS_TECNOLOGICAS.index(e.familia)),
    )
    return familias, con_familia, importe


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_proyectos_modulos(filters: ProyectosModulosFilters) -> ProyectosModulosResult:
    """Familias tecnológicas, módulos SAP (desglose de ERP), tipos de contrato y CPV."""
    log.info("analytics_proyectos_modulos_start", filters=filters.model_dump(exclude_none=True))
    repo_filters = _to_repo_filters(filters)

    familias, total_con_familia, importe_con_familia = _familias(repo_filters)
    menciones_familia = sum(e.count for e in familias)

    por_modulo, total_clasificados, importe_total_sap, total_sap = _repo.proyectos_modulos_stats(
        repo_filters,
        module_patterns=_MODULE_SQL_PATTERNS,
        all_pattern=_ALL_MODULES_PATTERN,
        solo_codigos=_CODIGOS_SAP,
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

    # Ámbito completo (mismo WHERE, licitaciones con y sin familia). Se reutiliza
    # el agregado ligero de tecnologías —COUNT(*) + un FILTER— en vez de
    # `overview_kpis`, que además calcularía SUM/AVG(importe) y un
    # COUNT(DISTINCT organo_contratacion) que aquí nadie consume.
    total_ambito, _sin_tecnologia = _repo.tecnologias_total_y_sin_clasificar(repo_filters)
    menciones_modulo = sum(e.count for e in modulos)
    pct_sap_con_modulo = total_clasificados / total_sap * 100 if total_sap else 0.0
    modulos_por_clasificada = menciones_modulo / total_clasificados if total_clasificados else 0.0

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
        familias=familias,
        total=total_ambito,
        total_con_familia=total_con_familia,
        menciones_familia=menciones_familia,
        pct_con_familia=round(total_con_familia / total_ambito * 100, 2) if total_ambito else 0.0,
        familias_por_licitacion=(
            round(menciones_familia / total_con_familia, 2) if total_con_familia else 0.0
        ),
        importe_con_familia=round(importe_con_familia, 2),
        ticket_medio_familia=(
            round(importe_con_familia / total_con_familia, 2) if total_con_familia else 0.0
        ),
        top_familia_yoy=_top_familia_yoy(repo_filters),
        fabricantes_sin_familia=_FABRICANTES_SIN_FAMILIA,
        modulos=modulos,
        total_sap=total_sap,
        total_clasificados=total_clasificados,
        menciones_modulo=menciones_modulo,
        pct_sap_con_modulo=round(pct_sap_con_modulo, 2),
        pct_match_portfolio=(
            round(total_clasificados / total_ambito * 100, 2) if total_ambito else 0.0
        ),
        modulos_por_clasificada=round(modulos_por_clasificada, 2),
        importe_total_sap=round(importe_total_sap, 2),
        ticket_medio_sap=round(ticket_medio_sap, 2),
        top_modulo_yoy=_top_modulo_yoy(repo_filters),
        tipos_proyecto=tipos_proyecto,
        tipo_estado=tipo_estado,
        cpv=cpv,
    )
    log.info(
        "analytics_proyectos_modulos_done",
        familias=len(result.familias),
        modulos=len(result.modulos),
        tipos=len(result.tipos_proyecto),
        cpv=len(result.cpv),
    )
    return result
