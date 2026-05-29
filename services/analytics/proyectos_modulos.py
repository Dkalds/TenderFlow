"""Proyectos & Modulos analytics — SAP module and project type breakdown."""

from __future__ import annotations

import re
from datetime import date

import pandas as pd
from pydantic import BaseModel, Field

from observability.logging import get_logger
from services.licitaciones import load_stats_dataframe

log = get_logger(__name__)


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


class ProyectosModulosResult(BaseModel):
    """Combined proyectos & modulos response."""

    modulos: list[ModuloEntry] = Field(default_factory=list)
    tipos_proyecto: list[ProyectoTipoEntry] = Field(default_factory=list)
    total_clasificados: int = 0


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


def _build_modulos(df: pd.DataFrame) -> tuple[list[ModuloEntry], int]:
    """Build module breakdown. Returns (entries, total_classified)."""
    if df.empty:
        return [], 0

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
            return [], 0
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
        return entries, total_clasificados

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
        return [], 0

    # Detect modules per row
    module_counts: dict[str, dict[str, float]] = {}
    classified_ids: set[int] = set()

    for idx, text in combined.items():
        modules = _detect_modules(str(text))
        if modules:
            classified_ids.add(int(idx))  # type: ignore[arg-type]
            imp = float(df.loc[idx, "importe"]) if pd.notna(df.loc[idx, "importe"]) else 0.0  # type: ignore[index]
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
    return entries, len(classified_ids)


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_proyectos_modulos(filters: ProyectosModulosFilters) -> ProyectosModulosResult:
    """Compute SAP module and project type breakdown."""
    log.info("analytics_proyectos_modulos_start", filters=filters.model_dump(exclude_none=True))
    df = _load_df()
    df = _apply_filters(df, filters)

    modulos, total_clasificados = _build_modulos(df)
    tipos_proyecto = _build_tipos_proyecto(df)

    result = ProyectosModulosResult(
        modulos=modulos,
        tipos_proyecto=tipos_proyecto,
        total_clasificados=total_clasificados,
    )
    log.info(
        "analytics_proyectos_modulos_done",
        modulos=len(result.modulos),
        tipos=len(result.tipos_proyecto),
    )
    return result
