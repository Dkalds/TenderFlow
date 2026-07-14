"""Servicio de licitaciones — acceso de lectura enriquecido.

Centraliza la lógica de carga, filtrado y paginación de licitaciones.
Delega en ``db/repositories/licitaciones.py`` para queries SQL y aplica
enriquecimiento (clasificadores, normalización) inline.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from db.repositories.licitaciones import LicitacionRepository
from observability.histograms import timed_query
from observability.logging import get_logger
from services._data_cache import SignalAwareCache

log = get_logger(__name__)

_repo = LicitacionRepository()

# Caché del DataFrame base (sin conversiones de tipo), única fuente de verdad
# para stats/analytics. Invalidada por TTL o por la señal de ingesta
# (shared.cache_signal). Analytics services llaman a load_stats_base_df() y
# reciben un .copy(); SignalAwareCache serializa los misses concurrentes, así
# que N threads con caché fría no construyen pd.DataFrame(rows) en paralelo.
#
# Antes existía además ``_stats_cache`` con la misma carga como list[dict] —
# nadie fuera de load_stats_base_df() consumía esa lista, así que mantenerla
# solo duplicaba en memoria el dataset full-table (~47k filas) sin necesidad.
# Ver postmortem OOM Render 2026-07-14.
_stats_df_cache: SignalAwareCache[pd.DataFrame] = SignalAwareCache()

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
    """Lista paginada de licitaciones para consumidores de la aplicación.

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


# ── Carga raw para consumidores de datos (sin enriquecimiento) ───────────


def load_raw(limit: int | None = None) -> list[dict[str, Any]]:
    """Carga licitaciones clasificadas (raw, sin enriquecimiento).

    Devuelve lista de dicts para que ``data_loader`` convierta a DataFrame
    y aplique transformaciones de presentación.
    """
    from db.database import init_db

    init_db()
    with timed_query("svc_load_raw"):
        return _repo.load_raw(columns=_RAW_COLUMNS, limit=limit)


def load_stats_dataframe() -> list[dict[str, Any]]:
    """Carga ligera de licitaciones para KPIs y stats (sin enriquecimiento), sin cachear.

    Cada llamada relee la BD; el único llamador en producción es
    :func:`load_stats_base_df`, que sí cachea el resultado (como DataFrame).
    """
    with timed_query("svc_load_stats"):
        return _repo.load_stats(_STATS_COLUMNS)


def load_stats_base_df() -> pd.DataFrame:
    """Devuelve una copia mutable del DataFrame base de licitaciones para analytics.

    El DataFrame base (sin conversiones de tipo) se construye una única vez y se
    invalida por TTL o por la señal de ingesta (``_stats_df_cache``). Cada
    llamada devuelve ``df.copy()`` para que el consumidor pueda mutar el
    DataFrame sin afectar la copia cacheada.
    """

    def _build() -> pd.DataFrame:
        return pd.DataFrame(load_stats_dataframe())

    return _stats_df_cache.get(_build).copy()


def clear_stats_cache() -> None:
    """Invalida la caché de :func:`load_stats_base_df`."""
    _stats_df_cache.clear()


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
    """Carga licitaciones enriquecidas desde la BD.

    Obtiene datos raw via ``load_raw()`` y aplica enriquecimiento
    (clasificadores, normalización, geo) inline.
    """
    from services.classification import (
        ESTADO_LABELS,
        TIPO_CONTRATO_LABELS,
        cpv_label,
        detect_modules,
        detect_project_type,
    )
    from shared.dates import month_start
    from shared.geo import nuts_to_ccaa

    rows = load_raw(limit=limit)
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    df["fecha_publicacion"] = pd.to_datetime(
        df["fecha_publicacion"],
        errors="coerce",
        format="mixed",
        utc=True,
    )
    df["importe"] = pd.to_numeric(df["importe"], errors="coerce")
    df["mes"] = month_start(df["fecha_publicacion"])
    df["anyo"] = df["fecha_publicacion"].dt.year

    # Enrichment
    desc_col = (
        df["descripcion"].fillna("")
        if "descripcion" in df.columns
        else pd.Series("", index=df.index)
    )
    text_blob = df["titulo"].fillna("") + " " + desc_col

    try:
        df["modulos"] = text_blob.apply(detect_modules)
        df["modulos_str"] = df["modulos"].str.join(", ")
    except Exception:
        df["modulos"] = [[] for _ in range(len(df))]
        df["modulos_str"] = ""

    try:
        df["tipo_proyecto"] = text_blob.apply(detect_project_type)
    except Exception:
        df["tipo_proyecto"] = "Otro"

    try:
        df["cpv_desc"] = df["cpv"].apply(cpv_label)
    except Exception:
        df["cpv_desc"] = ""

    try:
        stripped_estado = df["estado"].str.strip()
        df["estado_desc"] = (
            stripped_estado.map(ESTADO_LABELS).fillna(stripped_estado).fillna("Desconocido")
        )
    except Exception:
        df["estado_desc"] = ""

    try:
        stripped_tc = df["tipo_contrato"].str.strip()
        mapped_tc = stripped_tc.map(TIPO_CONTRATO_LABELS)
        unmapped = mapped_tc.isna() & stripped_tc.notna() & (stripped_tc != "")
        mapped_tc[unmapped] = "Tipo " + stripped_tc[unmapped]
        df["tipo_contrato_desc"] = mapped_tc.fillna("—")
    except Exception:
        df["tipo_contrato_desc"] = ""

    # Backfill CCAA
    if "ccaa" in df.columns and "nuts_code" in df.columns:
        try:
            mask = df["ccaa"].isna() & df["nuts_code"].notna()
            df.loc[mask, "ccaa"] = df.loc[mask, "nuts_code"].apply(nuts_to_ccaa)
        except Exception:
            pass

    for col in ("ccaa", "estado", "tipo_contrato", "provincia", "tipo_proyecto"):
        if col in df.columns:
            df[col] = df[col].astype("category")

    return df


def load_adjudicaciones(
    *,
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Proxy a la carga de adjudicaciones enriquecidas."""
    from services.adjudicaciones import load_adjudicaciones as _svc_adj

    return _svc_adj(limit=limit, ccaa_filter=ccaa_filter)


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
    """Búsqueda para el endpoint ``/ask`` (RAG).

    Con ``settings.RAG_HYBRID_ENABLED=True`` + backend Postgres + extra
    ``[ml]`` instalado: retrieval híbrido (FTS + similitud vectorial sobre
    ``documento_chunks``, fusión RRF) vía ``PgTsBackend.hybrid_search_docs``
    — cada doc trae además ``chunks`` (fuentes citables). En cualquier otro
    caso, o si el híbrido no encuentra nada (aún no hay pliegos chunkeados):
    FTS5/search_vector + LIKE fallback, **idéntico** al comportamiento
    histórico (plan Pliegos+RAG F9 — con el flag off este código no cambia
    de camino en absoluto).
    """
    from config import settings

    if settings.RAG_HYBRID_ENABLED:
        hybrid_docs = _try_hybrid_search(question, top_k, ccaa=ccaa, tecnologia=tecnologia)
        if hybrid_docs:
            return hybrid_docs

    docs = _repo.search_fts_docs(question, ccaa=ccaa, tecnologia=tecnologia, limit=top_k)
    if not docs:
        docs = _repo.search_like_for_ask(question, ccaa=ccaa, limit=top_k)
    return docs


def _try_hybrid_search(
    question: str,
    top_k: int,
    *,
    ccaa: str | None,
    tecnologia: str | None,
) -> list[dict[str, Any]] | None:
    """Intenta el retrieval híbrido; ``None`` si no aplica (no-Postgres, sin
    modelo de embeddings, o error) — el llamador cae al FTS puro."""
    from db.connection import is_postgres_backend

    if not is_postgres_backend():
        return None

    from services.embeddings import embeddings_available, encode_texts

    if not embeddings_available():
        return None

    try:
        query_embedding = encode_texts([question])[0].tolist()
    except Exception as e:
        log.debug("hybrid_search_embed_query_failed", error=str(e))
        return None

    from db.database import connect_read
    from db.search_backend import PgTsBackend

    try:
        with connect_read() as conn:
            docs = PgTsBackend().hybrid_search_docs(
                conn,
                question,
                query_embedding,
                ccaa=ccaa,
                tecnologia=tecnologia,
                limit=top_k,
            )
    except Exception as e:
        log.debug("hybrid_search_query_failed", error=str(e))
        return None
    return docs or None


def load_licitaciones_for_index() -> pd.DataFrame:
    """Load id_externo, titulo, descripcion for FAISS index building (§3.8)."""
    from db.database import connect, init_db

    init_db()
    with connect() as c:
        cursor = c.execute("SELECT id_externo, titulo, descripcion FROM licitaciones")
        rows = cursor.fetchall()
        cols = [d[0] for d in cursor.description]
    return pd.DataFrame(rows, columns=cols)
