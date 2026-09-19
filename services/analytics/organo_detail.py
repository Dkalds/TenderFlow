"""Organo detail analytics — drill-down for a single contracting body.

Consume proyecciones ACOTADAS al órgano pedido (ADR-023):
``AggregateRepository.licitaciones_por_organo`` y tres agregados de
``AdjudicacionRepository`` (top adjudicatarios, lead-time mediano y mejor
adjudicación de los mejor puntuados), todos con los filtros del ámbito
en el ``WHERE`` — todo lo que pinta el panel (KPIs, adjudicatarios, lead-time,
estacionalidad y ranking) mide el mismo subconjunto. Hasta 2026-08 cargaba
las dos tablas completas a pandas en el proceso API — bloqueado en Render por
el cortacircuitos full-table, que dejaba este endpoint vacío en producción.
El scoring simple, la estacionalidad y el lead-time siguen en pandas sobre el
subconjunto acotado. De paso viven dos campos que llegaban siempre nulos: la
identidad del adjudicatario usa el maestro canónico cuando existe (el código
prefería ``nombre_canonico``, pero el loader raw nunca lo traía) y
``baja_pct`` se calcula de ``importe_adjudicado``/``importe_licitacion`` (el
loader raw tampoco traía esa columna derivada).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from db.repositories.adjudicaciones import AdjudicacionRepository
from db.repositories.aggregates import AggregateRepository, LicitacionesFilters
from observability.logging import get_logger
from services.analytics.scoring import score_dataframe
from services.analytics.scoring_signals import load_importe_percentiles
from services.classification import (
    ESTADO_LABELS,
    cpv_label,
    detect_project_type,
    tipo_contrato_label,
)

log = get_logger(__name__)

_repo = AggregateRepository()
_adj_repo = AdjudicacionRepository()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class OrganoDetailFilters(BaseModel):
    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    ccaa: str | None = None
    tecnologia: str | None = None
    estado: str | None = None
    importe_min: float | None = None
    solo_abiertas: bool = False


class OrganoKpis(BaseModel):
    total_licitaciones: int = 0
    importe_total: float = 0.0
    importe_medio: float = 0.0
    pct_adjudicado: float = 0.0
    lead_time_medio: float | None = None
    top_adjudicatario: str | None = None
    top_adj_importe: float = 0.0


class TopAdjudicatario(BaseModel):
    nombre: str
    count: int
    importe: float


class Estacionalidad(BaseModel):
    mes_numero: int
    count: int


class TopScored(BaseModel):
    id_externo: str
    titulo: str | None = None
    importe: float | None = None
    score: float
    ccaa: str | None = None
    estado: str | None = None
    estado_desc: str | None = None
    banda: str | None = None
    empresa: str | None = None
    baja_pct: float | None = None
    fecha_adjudicacion: str | None = None
    modulos_str: str | None = None
    url: str | None = None
    tipo_proyecto: str | None = None
    tipo_contrato_desc: str | None = None
    cpv_desc: str | None = None


class OrganoDetailResult(BaseModel):
    kpis: OrganoKpis = Field(default_factory=OrganoKpis)
    top_adjudicatarios: list[TopAdjudicatario] = Field(default_factory=list)
    estacionalidad: list[Estacionalidad] = Field(default_factory=list)
    top_scored: list[TopScored] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_repo_filters(filters: OrganoDetailFilters) -> LicitacionesFilters:
    return LicitacionesFilters(
        fecha_desde=filters.fecha_desde.isoformat() if filters.fecha_desde else None,
        fecha_hasta=filters.fecha_hasta.isoformat() if filters.fecha_hasta else None,
        ccaa=filters.ccaa,
        tecnologia=filters.tecnologia,
        estado=filters.estado,
        importe_min=filters.importe_min,
        solo_abiertas=filters.solo_abiertas,
    )


def _lead_time_median(adj_df: pd.DataFrame) -> float | None:
    """Mediana de días entre publicación y adjudicación.

    **Referencia de semántica**, no el camino de producción: desde C3.2 el
    drill-down la pide agregada en SQL
    (``AdjudicacionRepository.lead_time_mediano_por_organo``), y
    ``tests/test_organo_detail_sql_paridad.py`` compara las dos sobre la misma
    muestra. Se conserva porque es la definición legible de lo que el SQL
    tiene que devolver.

    Espera un DataFrame de adjudicaciones con columnas ``fecha_publicacion``
    (de la licitación asociada) y ``fecha_adjudicacion``. Solo cuenta diferencias
    positivas. Devuelve ``None`` si no hay pares válidos.
    """
    if adj_df.empty:
        return None
    if "fecha_publicacion" not in adj_df.columns or "fecha_adjudicacion" not in adj_df.columns:
        return None
    fp = pd.to_datetime(adj_df["fecha_publicacion"], errors="coerce", utc=True)
    fa = pd.to_datetime(adj_df["fecha_adjudicacion"], errors="coerce", utc=True)
    diff = (fa - fp).dt.days
    valid = diff[diff > 0]
    if valid.empty:
        return None
    return float(valid.median())


def _numero(valor: object) -> float | None:
    """``float`` de un importe, o ``None`` si falta o no es numérico (``to_numeric`` coerce)."""
    if valor is None:
        return None
    try:
        numero = float(str(valor))
    except ValueError:
        return None
    return None if math.isnan(numero) else numero


def _adj_lookup_for(filas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Empresa, baja y fecha de la mejor adjudicación de cada licitación.

    ``filas`` ya viene con una adjudicación por licitación —la de mayor
    importe— desde ``mejor_adjudicacion_por_licitacion``; aquí sólo se deriva
    la baja porcentual y se formatea la fecha.
    """
    lookup: dict[str, dict[str, Any]] = {}
    for row in filas:
        importe_lic = _numero(row.get("importe_licitacion"))
        importe_adj = _numero(row.get("importe_adjudicado"))
        baja = None
        if importe_adj is not None and importe_lic is not None and importe_lic > 0:
            baja = float((1 - importe_adj / importe_lic) * 100)
        fecha_adj = None
        if pd.notna(row.get("fecha_adjudicacion")):
            try:
                fecha_adj = str(pd.Timestamp(row["fecha_adjudicacion"]).strftime("%d/%m/%Y"))
            except (ValueError, TypeError):
                pass
        lookup[str(row["licitacion_id"])] = {
            "empresa": str(row["nombre"]) if pd.notna(row.get("nombre")) else None,
            "baja_pct": baja,
            "fecha_adjudicacion": fecha_adj,
        }
    return lookup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_organo_detail(organo: str, filters: OrganoDetailFilters) -> OrganoDetailResult:
    """Drill-down for a single contracting body."""
    log.info("analytics_organo_detail_start", organo=organo)
    repo_filters = _to_repo_filters(filters)
    rows = _repo.licitaciones_por_organo(organo, repo_filters)
    if not rows:
        return OrganoDetailResult()

    df = pd.DataFrame(rows)
    df = df.assign(
        fecha_publicacion=pd.to_datetime(df["fecha_publicacion"], errors="coerce", utc=True),
        importe=pd.to_numeric(df["importe"], errors="coerce"),
        # Nombre que espera `_score_row` para la dimensión plazo.
        fecha_limite_dt=pd.to_datetime(df["fecha_limite"], errors="coerce", utc=True),
        id_externo=df["id_externo"].astype(str),
    )

    # KPIs
    total = len(df)
    importe_total = float(df["importe"].sum(skipna=True))
    notna_imp = int(df["importe"].notna().sum())
    importe_medio = float(importe_total / notna_imp) if notna_imp else 0.0
    adjudicado = len(df[df["estado"] == "ADJ"])
    pct_adj = (adjudicado / total * 100) if total else 0.0

    kpis = OrganoKpis(
        total_licitaciones=total,
        importe_total=importe_total,
        importe_medio=importe_medio,
        pct_adjudicado=pct_adj,
        lead_time_medio=None,
    )

    # Adjudicatarios del órgano, con el mismo ámbito que las licitaciones de
    # arriba: si el panel dice "13 licitaciones SAP", su top adjudicatario
    # tiene que salir de esas 13. Ranking y lead-time se agregan en SQL (C3.2):
    # antes se traían todas las adjudicaciones del órgano a un DataFrame para
    # quedarse con veinte filas y una mediana.
    top_adj = [
        TopAdjudicatario(
            nombre=str(fila["nombre"]),
            count=int(fila["count"]),
            importe=float(fila["importe"] or 0),
        )
        for fila in _adj_repo.top_adjudicatarios_por_organo(organo, repo_filters)
    ]
    kpis.lead_time_medio = _adj_repo.lead_time_mediano_por_organo(organo, repo_filters)

    # Top adjudicatario en kpis
    if top_adj:
        kpis.top_adjudicatario = top_adj[0].nombre
        kpis.top_adj_importe = top_adj[0].importe

    # Estacionalidad
    estacionalidad: list[Estacionalidad] = []
    valid_dates = df.dropna(subset=["fecha_publicacion"])
    if not valid_dates.empty:
        valid_dates = valid_dates.copy()
        valid_dates["mes_num"] = valid_dates["fecha_publicacion"].dt.month
        n_years = max(valid_dates["fecha_publicacion"].dt.year.nunique(), 1)
        mes_counts = valid_dates.groupby("mes_num").size()
        estacionalidad = [
            Estacionalidad(mes_numero=int(str(m)), count=round(c / n_years))
            for m, c in mes_counts.items()
        ]

    # Top scored — el mismo motor que el Radar, enriquecido con adjudicación.
    #
    # Hasta 2026-08 esto lo hacía un `_simple_score` propio, superviviente del
    # scoring pre-RFC: sumaba 5 puntos por cada keyword SAP del título, 10 si
    # el estado estaba en una allowlist que dejaba fuera `ADM` (el más común),
    # y bandas A/B/C/D incomparables con las del resto del producto. Dos
    # rankings distintos para la misma licitación, y el que se veía aquí era el
    # que el RFC de scoring genérico había eliminado.
    scored_df = score_dataframe(df, df, importe_percentiles=load_importe_percentiles())
    df = df.merge(scored_df.rename(columns={"score": "_score"}), on="id_externo", how="left")
    df["_score"] = df["_score"].fillna(0)
    top_scored_df = df.nlargest(30, "_score").copy()
    adj_lookup = _adj_lookup_for(
        _adj_repo.mejor_adjudicacion_por_licitacion(
            organo, [str(i) for i in top_scored_df["id_externo"]], repo_filters
        )
    )

    top_scored = []
    for _, row in top_scored_df.iterrows():
        eid = str(row.get("id_externo", ""))
        adj_info = adj_lookup.get(eid, {})
        score = float(row["_score"])
        estado_raw = str(row["estado"]) if pd.notna(row.get("estado")) else None
        titulo_raw = str(row["titulo"]) if pd.notna(row.get("titulo")) else None
        tipo_contrato_raw = (
            str(row["tipo_contrato"]) if pd.notna(row.get("tipo_contrato")) else None
        )
        cpv_raw = str(row["cpv"]) if pd.notna(row.get("cpv")) else None
        top_scored.append(
            TopScored(
                id_externo=eid,
                titulo=titulo_raw,
                importe=float(row["importe"]) if pd.notna(row.get("importe")) else None,
                score=score,
                banda=str(row["band"]) if pd.notna(row.get("band")) else None,
                ccaa=str(row["ccaa"]) if pd.notna(row.get("ccaa")) else None,
                estado=estado_raw,
                estado_desc=ESTADO_LABELS.get(estado_raw.strip(), estado_raw)
                if estado_raw
                else None,
                # La proyección de stats nunca trajo modulos_str (derivado del
                # loader enriquecido, sin uso aquí) — se preserva el None.
                modulos_str=None,
                url=str(row["url"]) if pd.notna(row.get("url")) else None,
                tipo_proyecto=detect_project_type(titulo_raw) if titulo_raw else None,
                tipo_contrato_desc=tipo_contrato_label(tipo_contrato_raw)
                if tipo_contrato_raw
                else None,
                cpv_desc=cpv_label(cpv_raw) if cpv_raw else None,
                empresa=adj_info.get("empresa"),
                baja_pct=adj_info.get("baja_pct"),
                fecha_adjudicacion=adj_info.get("fecha_adjudicacion"),
            )
        )

    log.info("analytics_organo_detail_done", total=total)
    return OrganoDetailResult(
        kpis=kpis,
        top_adjudicatarios=top_adj,
        estacionalidad=estacionalidad,
        top_scored=top_scored,
    )
