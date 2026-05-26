"""Servicio de licitaciones — acceso de lectura enriquecido.

Centraliza la lógica de carga, filtrado y paginación de licitaciones.
Delega en ``db/repositories/licitaciones.py`` para queries SQL y en
``dashboard/data_loader.py`` para enriquecimiento DataFrame (transición gradual).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from db.repositories.licitaciones import LicitacionRepository
from observability.histograms import timed_query
from observability.logging import get_logger

log = get_logger(__name__)

_repo = LicitacionRepository()

# ── Columnas reutilizadas por load_raw / stats ───────────────────────────
_RAW_COLUMNS = (
    "id_externo, titulo, organo_contratacion, importe, estado, "
    "fecha_publicacion, ccaa, nuts_code, cpv, url, tecnologia, "
    "tipo_contrato, moneda, provincia, duracion_valor, duracion_unidad, "
    "fecha_limite, fecha_inicio, fecha_fin, fecha_extraccion"
)

_STATS_COLUMNS = (
    "id_externo, titulo, organo_contratacion, importe, estado, "
    "fecha_publicacion, ccaa, nuts_code, cpv, url, tecnologia, tipo_contrato, "
    "moneda, provincia, fecha_limite, fecha_inicio, fecha_fin, fecha_extraccion"
)


# ── API paginada (usada por la REST API) ─────────────────────────────────


def list_licitaciones(
    *,
    q: str | None = None,
    estado: str | None = None,
    ccaa: str | None = None,
    tecnologia: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    limit: int = 50,
    offset: int = 0,
    sort: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Lista paginada de licitaciones (API/dashboard).

    Returns:
        (items, total) donde items son dicts con campos de resumen.
    """
    with timed_query("svc_list_licitaciones"):
        return _repo.list_paginated(
            q=q,
            estado=estado,
            ccaa=ccaa,
            tecnologia=tecnologia,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            limit=limit,
            offset=offset,
            sort=sort,
        )


def get_licitacion_detail(id_externo: str) -> dict[str, Any] | None:
    """Detalle completo de una licitación por ID."""
    with timed_query("svc_get_licitacion_detail"):
        return _repo.get_by_id(id_externo)


# ── Carga raw para el dashboard (sin enriquecimiento) ────────────────────


def load_raw(limit: int | None = None) -> list[dict[str, Any]]:
    """Carga licitaciones clasificadas (raw, sin enriquecimiento).

    Devuelve lista de dicts para que ``data_loader`` convierta a DataFrame
    y aplique transformaciones Streamlit.
    """
    from db.database import init_db

    init_db()
    with timed_query("svc_load_raw"):
        return _repo.load_raw(columns=_RAW_COLUMNS, limit=limit)


def load_stats_dataframe() -> list[dict[str, Any]]:
    """Carga ligera de licitaciones para KPIs y stats (sin enriquecimiento)."""
    with timed_query("svc_load_stats"):
        return _repo.load_stats(_STATS_COLUMNS)


# ── Búsquedas especializadas ─────────────────────────────────────────────


def load_uncertainty_zone(lo: float, hi: float, limit: int) -> list[dict[str, Any]]:
    """Licitaciones con ``ml_proba`` en zona de incertidumbre (active learning)."""
    return _repo.load_uncertainty_zone(lo, hi, limit)


def search_fts_ids(query: str, limit: int = 1000) -> list[str] | None:
    """Busca con FTS5 y devuelve id_externo ordenados por bm25 rank.

    Returns ``None`` si FTS no está disponible o la query falla (fallback a str.contains).
    """
    return _repo.search_fts_ids(query, limit)


# ── Proxies de conveniencia (transición gradual) ─────────────────────────


def load_dataframe(limit: int | None = None) -> pd.DataFrame:
    """Proxy al data_loader existente — transición gradual hacia services.

    Las pages siguen usando ``dashboard.data_loader.load_dataframe()`` directamente
    hasta que todas migren. Este wrapper permite que el código nuevo use la capa
    de servicios de forma transparente.
    """
    from dashboard.data_loader import load_dataframe as _dl_load

    return _dl_load(limit=limit)


def load_adjudicaciones(
    *,
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Proxy a la carga de adjudicaciones del data_loader."""
    from dashboard.data_loader import load_adjudicaciones as _dl_adj

    return _dl_adj(limit=limit, ccaa_filter=ccaa_filter)


# ── Búsqueda avanzada (POST /licitaciones/search) ────────────────────────


def search_advanced(
    *,
    q: str | None = None,
    estado: list[str] | None = None,
    ccaa: list[str] | None = None,
    tecnologia: list[str] | None = None,
    importe_min: float | None = None,
    importe_max: float | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    sort: str | None = None,
    limit: int = 50,
    offset: int = 0,
    with_total: bool = True,
) -> tuple[list[dict[str, Any]], int]:
    """Búsqueda avanzada con criterios complejos (multi-CCAA, rangos de importe...).

    Usada por el endpoint POST ``/licitaciones/search``.
    Delega a ``LicitacionRepository.search_advanced`` para construcción type-safe
    de queries via SQLAlchemy Core.
    """
    with timed_query("svc_search_advanced"):
        return _repo.search_advanced(
            q=q,
            estado=estado,
            ccaa=ccaa,
            tecnologia=tecnologia,
            importe_min=importe_min,
            importe_max=importe_max,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            sort=sort,
            limit=limit,
            offset=offset,
            with_total=with_total,
        )


# ── Carga para drift detection ───────────────────────────────────────────


def load_drift_window(days: int, offset_days: int = 0) -> list[dict[str, Any]]:
    """Carga licitaciones de un rango de días para drift detection."""
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=offset_days + days)).isoformat()[:10]
    end = (datetime.now(UTC) - timedelta(days=offset_days)).isoformat()[:10]
    return _repo.load_drift_window(cutoff, end)


def get_history(id_externo: str, limit: int = 50) -> list[dict[str, Any]]:
    """Devuelve el historial de cambios de una licitación."""
    return _repo.get_history(id_externo, limit)


def fetch_recent(since_iso: str, limit: int = 20) -> list[dict[str, Any]]:
    """Licitaciones publicadas/actualizadas desde ``since_iso`` (para SSE stream)."""
    return _repo.fetch_recent(
        since_extraccion=since_iso,
        since_actualizacion=since_iso,
        limit=limit,
    )


def fetch_for_pdf(
    *,
    ccaa: str | None = None,
    estado: str | None = None,
    q: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Carga licitaciones para exportación PDF."""
    return _repo.fetch_for_pdf(ccaa=ccaa, estado=estado, q=q, limit=limit)


def search_for_ask(
    question: str,
    top_k: int,
    ccaa: str | None = None,
    tecnologia: str | None = None,
) -> list[dict[str, Any]]:
    """Búsqueda FTS5 + LIKE fallback para el endpoint /ask (RAG)."""
    docs = _repo.search_fts_docs(question, ccaa=ccaa, tecnologia=tecnologia, limit=top_k)
    if not docs:
        docs = _repo.search_like_for_ask(question, ccaa=ccaa, limit=top_k)
    return docs
