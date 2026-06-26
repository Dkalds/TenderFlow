"""Proyectos & Modulos analytics — SAP module and project type breakdown."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.classification import cpv_label, estado_label
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)

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

# Pre-compile patterns for performance
_MODULE_PATTERNS: dict[str, re.Pattern[str]] = {
    mod: re.compile("|".join(re.escape(kw) for kw in keywords), re.IGNORECASE)
    for mod, keywords in _SAP_MODULES.items()
}


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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_df() -> pd.DataFrame:
    rows = load_stats_dataframe()
    df = pd.DataFrame(rows)
    if not df.empty:
        df["fecha_publicacion"] = pd.to_datetime(
            df["fecha_publicacion"],
            errors="coerce",
            utc=True,
        )
        df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    return df


def _apply_filters(df: pd.DataFrame, filters: ProyectosModulosFilters) -> pd.DataFrame:
    if df.empty:
        return df
    if filters.fecha_desde is not None:
        ts = pd.Timestamp(filters.fecha_desde, tz="UTC")
        df = df[df["fecha_publicacion"] >= ts]
    if filters.fecha_hasta is not None:
        ts = pd.Timestamp(filters.fecha_hasta, tz="UTC")
        df = df[df["fecha_publicacion"] <= ts]
    if filters.tecnologia:
        df = df[df["tecnologia"] == filters.tecnologia]
    return df


def _detect_modules(text: str) -> list[str]:
    """Detect SAP modules mentioned in a text string."""
    if not text:
        return []
    found = []
    for mod, pattern in _MODULE_PATTERNS.items():
        if pattern.search(text):
            found.append(mod)
    return found


def _build_modulos(df: pd.DataFrame) -> tuple[list[ModuloEntry], int, float]:
    """Build module breakdown. Returns (entries, total_classified, importe_distinct).

    `importe_distinct` suma el importe de cada licitación clasificada UNA vez
    (no por módulo), para KPIs a nivel licitación sin doble conteo multi-módulo.
    """
    if df.empty:
        return [], 0, 0.0

    # Check if explicit module column exists
    if "modulo_sap" in df.columns:
        col = "modulo_sap"
    elif "modulos" in df.columns:
        col = "modulos"
    else:
        col = None

    if col is not None:
        classified = df.dropna(subset=[col])
        classified = classified[classified[col].astype(str).str.strip() != ""]
        total_clasificados = len(classified)
        if classified.empty:
            return [], 0, 0.0
        # Importe a nivel licitación distinct (cada fila = una licitación aquí).
        importe_distinct = float(classified["importe"].sum(skipna=True) or 0.0)
        g = (
            classified.groupby(col)
            .agg(count=("id_externo", "count"), importe=("importe", "sum"))
            .sort_values("count", ascending=False)
            .reset_index()
        )
        entries = [
            ModuloEntry(
                modulo=row[col], count=int(row["count"]), importe=float(row["importe"] or 0)
            )
            for _, row in g.iterrows()
        ]
        return entries, total_clasificados, importe_distinct

    # Fallback: detect modules from titulo + descripcion
    for c in ["titulo", "descripcion"]:
        if c in df.columns:
            break

    # Combine titulo and descripcion if both exist
    if "titulo" in df.columns and "descripcion" in df.columns:
        combined = (
            df["titulo"].fillna("").astype(str) + " " + df["descripcion"].fillna("").astype(str)
        )
    elif "titulo" in df.columns:
        combined = df["titulo"].fillna("").astype(str)
    elif "descripcion" in df.columns:
        combined = df["descripcion"].fillna("").astype(str)
    else:
        return [], 0, 0.0

    # Detect modules per row
    module_counts: dict[str, dict[str, float]] = {}
    classified_ids: set[int] = set()
    distinct_importe = 0.0

    for i, (idx, text) in enumerate(combined.items()):
        modules = _detect_modules(str(text))
        if modules:
            classified_ids.add(int(str(idx)))
            val = df.iloc[i].get("importe", 0.0)
            imp = float(str(val)) if pd.notna(val) else 0.0
            distinct_importe += imp  # una vez por licitación, no por módulo
            for mod in modules:
                if mod not in module_counts:
                    module_counts[mod] = {"count": 0, "importe": 0.0}
                module_counts[mod]["count"] += 1
                module_counts[mod]["importe"] += imp

    entries = sorted(
        [
            ModuloEntry(modulo=mod, count=int(vals["count"]), importe=vals["importe"])
            for mod, vals in module_counts.items()
        ],
        key=lambda e: e.count,
        reverse=True,
    )
    return entries, len(classified_ids), distinct_importe


def _build_tipos_proyecto(df: pd.DataFrame) -> list[ProyectoTipoEntry]:
    """Build project type breakdown from tipo_contrato column."""
    if df.empty or "tipo_contrato" not in df.columns:
        return []

    classified = df.dropna(subset=["tipo_contrato"])
    classified = classified[classified["tipo_contrato"].astype(str).str.strip() != ""]
    if classified.empty:
        return []

    g = (
        classified.groupby("tipo_contrato")
        .agg(count=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("count", ascending=False)
        .reset_index()
    )
    return [
        ProyectoTipoEntry(
            tipo=row["tipo_contrato"],
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
        )
        for _, row in g.iterrows()
    ]


def _combined_text(df: pd.DataFrame) -> pd.Series | None:
    """Build the title (+ description) text column used for module detection."""
    if "titulo" in df.columns and "descripcion" in df.columns:
        return df["titulo"].fillna("").astype(str) + " " + df["descripcion"].fillna("").astype(str)
    if "titulo" in df.columns:
        return df["titulo"].fillna("").astype(str)
    if "descripcion" in df.columns:
        return df["descripcion"].fillna("").astype(str)
    return None


def _top_modulo_yoy(df: pd.DataFrame) -> TopModuloYoY | None:
    """Fastest-growing module: last 12 months vs the previous 12 months."""
    if df.empty or "fecha_publicacion" not in df.columns:
        return None
    work = df.dropna(subset=["fecha_publicacion"]).copy()
    if work.empty:
        return None
    text = _combined_text(work)
    if text is None:
        return None

    hoy = pd.Timestamp.now("UTC")
    in_act = work["fecha_publicacion"] >= (hoy - pd.Timedelta(days=365))
    in_prev = (work["fecha_publicacion"] < (hoy - pd.Timedelta(days=365))) & (
        work["fecha_publicacion"] >= (hoy - pd.Timedelta(days=730))
    )

    act: dict[str, int] = {}
    prev: dict[str, int] = {}
    for txt, a, p in zip(text, in_act, in_prev, strict=False):
        if not (a or p):
            continue
        for mod in _detect_modules(str(txt)):
            if a:
                act[mod] = act.get(mod, 0) + 1
            elif p:
                prev[mod] = prev.get(mod, 0) + 1

    if not act:
        return None

    # Reduce noise: prefer modules with at least 2 mentions this year.
    candidates = {m: n for m, n in act.items() if n >= 2} or act

    best_mod: str | None = None
    best_growth = -1e18
    best_n = 0
    for mod, n_act in candidates.items():
        n_prev = prev.get(mod, 0)
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


def _build_tipo_estado(df: pd.DataFrame) -> list[TipoEstadoEntry]:
    """Cross-tab of tipo_contrato x estado (stacked-bar equivalent of the sunburst)."""
    if df.empty or "tipo_contrato" not in df.columns or "estado" not in df.columns:
        return []
    sub = df.dropna(subset=["tipo_contrato"])
    sub = sub[sub["tipo_contrato"].astype(str).str.strip() != ""]
    if sub.empty:
        return []
    g = sub.groupby(["tipo_contrato", "estado"]).size().reset_index(name="n")
    return [
        TipoEstadoEntry(
            tipo=str(row["tipo_contrato"]),
            estado=estado_label(row["estado"]),
            n=int(row["n"]),
        )
        for _, row in g.iterrows()
    ]


def _build_cpv(df: pd.DataFrame) -> list[CpvEntry]:
    """Top-N CPV codes by tender count, with readable descriptions."""
    if df.empty or "cpv" not in df.columns:
        return []
    sub = df.dropna(subset=["cpv"])
    sub = sub[sub["cpv"].astype(str).str.strip() != ""]
    if sub.empty:
        return []
    g = (
        sub.groupby("cpv")
        .agg(count=("id_externo", "count"), importe=("importe", "sum"))
        .sort_values("count", ascending=False)
        .head(_TOP_CPV)
        .reset_index()
    )
    return [
        CpvEntry(
            cpv=str(row["cpv"]),
            cpv_desc=cpv_label(str(row["cpv"])),
            count=int(row["count"]),
            importe=float(row["importe"] or 0),
        )
        for _, row in g.iterrows()
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_proyectos_modulos(filters: ProyectosModulosFilters) -> ProyectosModulosResult:
    """Compute SAP module and project type breakdown."""
    log.info("analytics_proyectos_modulos_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    modulos, total_clasificados, importe_total_sap = _build_modulos(df)
    tipos_proyecto = _build_tipos_proyecto(df)
    ticket_medio_sap = importe_total_sap / total_clasificados if total_clasificados else 0.0

    result = ProyectosModulosResult(
        modulos=modulos,
        tipos_proyecto=tipos_proyecto,
        total_clasificados=total_clasificados,
        importe_total_sap=round(importe_total_sap, 2),
        ticket_medio_sap=round(ticket_medio_sap, 2),
        top_modulo_yoy=_top_modulo_yoy(df),
        tipo_estado=_build_tipo_estado(df),
        cpv=_build_cpv(df),
    )
    log.info(
        "analytics_proyectos_modulos_done",
        modulos=len(result.modulos),
        tipos=len(result.tipos_proyecto),
        cpv=len(result.cpv),
    )
    return result
