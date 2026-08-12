"""Servicio de licitaciones — acceso de lectura para API y jobs.

Centraliza la lógica de carga, filtrado y paginación de licitaciones,
delegando en ``db/repositories/licitaciones.py`` para queries SQL. Las
analíticas ya NO pasan por aquí: agregan en Postgres vía
``db/repositories/aggregates.py`` (ADR-023) — los loaders full-table
(``load_stats_base_df``/``load_dataframe`` y sus cachés) se retiraron al
migrar el último consumidor, junto con el cortacircuitos de Render que los
bloqueaba.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from db.repositories.licitaciones import LicitacionRepository
from observability.histograms import timed_query
from observability.logging import get_logger

log = get_logger(__name__)

_repo = LicitacionRepository()


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


# ── Búsquedas especializadas ─────────────────────────────────────────────


def load_uncertainty_zone(lo: float, hi: float, limit: int) -> list[dict[str, Any]]:
    """Licitaciones con ``ml_proba`` en zona de incertidumbre (active learning)."""
    return _repo.load_uncertainty_zone(lo, hi, limit)


def search_fts_ids(query: str, limit: int = 1000) -> list[str] | None:
    """Busca con FTS5 y devuelve id_externo ordenados por bm25 rank.

    Returns ``None`` si FTS no está disponible o la query falla (fallback a str.contains).
    """
    return _repo.search_fts_ids(query, limit)


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
    tecnologia: str | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Carga licitaciones para exportación PDF."""
    return _repo.fetch_for_pdf(
        ccaa=ccaa,
        estado=estado,
        q=q,
        tecnologia=tecnologia,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        limit=limit,
    )


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
    """Intenta el retrieval híbrido; ``None`` si no aplica (sin modelo de
    embeddings, o error) — el llamador cae al FTS puro."""
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
