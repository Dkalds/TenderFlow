"""Servicio de licitaciones — acceso de lectura enriquecido.

Centraliza la lógica de carga, filtrado y paginación de licitaciones.
Delega en ``db/repositories/licitaciones.py`` para queries SQL y en
``dashboard/data_loader.py`` para enriquecimiento DataFrame (transición gradual).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from db.database import connect_read, fts_available, init_db
from db.repositories.base import rows_to_dicts
from db.repositories.licitaciones import LicitacionRepository
from observability.histograms import timed_query
from observability.logging import get_logger
from services.investigador.search_engine import escape_fts5

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
    init_db()
    sql = (
        "SELECT " + _RAW_COLUMNS + " FROM licitaciones "
        "WHERE tecnologia IS NOT NULL AND tecnologia != '' "
        "ORDER BY fecha_publicacion DESC"
    )
    params: list[Any] = []
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    with timed_query("svc_load_raw"), connect_read() as c:
        return rows_to_dicts(c.execute(sql, params))


def load_stats_dataframe() -> list[dict[str, Any]]:
    """Carga ligera de licitaciones para KPIs y stats (sin enriquecimiento)."""
    with timed_query("svc_load_stats"), connect_read() as c:
        cur = c.execute("SELECT " + _STATS_COLUMNS + " FROM licitaciones")
        return rows_to_dicts(cur)


# ── Búsquedas especializadas ─────────────────────────────────────────────


def load_uncertainty_zone(lo: float, hi: float, limit: int) -> list[dict[str, Any]]:
    """Licitaciones con ``ml_proba`` en zona de incertidumbre (active learning)."""
    with connect_read() as c:
        cur = c.execute(
            "SELECT id_externo, titulo, descripcion, organo_contratacion, importe, "
            "fecha_publicacion, cpv, ml_proba FROM licitaciones "
            "WHERE ml_proba IS NOT NULL AND ml_proba BETWEEN ? AND ? "
            "ORDER BY (importe IS NULL), importe DESC, ml_proba LIMIT ?",
            (lo, hi, limit),
        )
        return rows_to_dicts(cur)


def search_fts_ids(query: str, limit: int = 1000) -> list[str] | None:
    """Busca con FTS5 y devuelve id_externo ordenados por bm25 rank.

    Returns ``None`` si FTS no está disponible o la query falla (fallback a str.contains).
    """
    if not fts_available() or not query.strip():
        return None
    try:
        fts_query = escape_fts5(query)
        with connect_read() as c:
            cur = c.execute(
                "SELECT f.id_externo FROM licitaciones_fts f "
                "WHERE licitaciones_fts MATCH ? ORDER BY rank LIMIT ?",
                [fts_query, limit],
            )
            return [row[0] for row in cur.fetchall()]
    except Exception as exc:
        log.debug("fts_search_fallback", error=str(exc), query=query)
        return None


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
    with connect_read() as c:
        cur = c.execute(
            "SELECT importe, cpv, ccaa, tecnologia, estado "
            "FROM licitaciones "
            "WHERE fecha_publicacion >= ? AND fecha_publicacion <= ?",
            (cutoff, end),
        )
        return rows_to_dicts(cur)
