"""Servicio de licitaciones — acceso de lectura para API y jobs.

Centraliza la lógica de carga, filtrado y paginación de licitaciones,
delegando en ``db/repositories/licitaciones.py`` para queries SQL. Las
analíticas ya NO pasan por aquí: agregan en Postgres vía
``db/repositories/aggregates/`` (ADR-023) — los loaders full-table
(``load_stats_base_df``/``load_dataframe`` y sus cachés) se retiraron al
migrar el último consumidor, junto con el cortacircuitos de Render que los
bloqueaba.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from db.repositories.licitaciones import (
    DriftRow,
    ExportPdfRow,
    HistorialRow,
    LicitacionRepository,
    LicitacionResumenRow,
    RecienteRow,
    ZonaIncertidumbreRow,
)
from observability.histograms import timed_query
from shared.dto import FiltrosLicitacion

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
) -> tuple[list[LicitacionResumenRow], int]:
    """Lista paginada de licitaciones para consumidores de la aplicación.

    Returns:
        (items, total) donde items son dicts con campos de resumen.
    """
    with timed_query("svc_list_licitaciones"):
        filtros = FiltrosLicitacion(
            q=q,
            estado=estado,
            ccaa=ccaa,
            tecnologia=tecnologia,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )
        return _repo.list_paginated(filtros, limit=limit, offset=offset, sort=sort)


def get_licitacion_detail(id_externo: str) -> dict[str, Any] | None:
    """Detalle completo de una licitación por ID."""
    with timed_query("svc_get_licitacion_detail"):
        return _repo.get_by_id(id_externo)


# ── Búsquedas especializadas ─────────────────────────────────────────────


def load_uncertainty_zone(lo: float, hi: float, limit: int) -> list[ZonaIncertidumbreRow]:
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
) -> tuple[list[LicitacionResumenRow], int]:
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


def load_drift_window(days: int, offset_days: int = 0) -> list[DriftRow]:
    """Carga licitaciones de un rango de días para drift detection."""
    from datetime import UTC, datetime, timedelta

    cutoff = (datetime.now(UTC) - timedelta(days=offset_days + days)).isoformat()[:10]
    end = (datetime.now(UTC) - timedelta(days=offset_days)).isoformat()[:10]
    return _repo.load_drift_window(cutoff, end)


def get_history(id_externo: str, limit: int = 50) -> list[HistorialRow]:
    """Devuelve el historial de cambios de una licitación."""
    return _repo.get_history(id_externo, limit)


def fetch_recent(since_iso: str, limit: int = 20) -> list[RecienteRow]:
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
    importe_min: float | None = None,
    importe_max: float | None = None,
    provincia: str | None = None,
    procedimiento: str | None = None,
    solo_abiertas: bool = False,
    cierre_desde: str | None = None,
    cierre_hasta: str | None = None,
    limit: int = 500,
) -> list[ExportPdfRow]:
    """Carga licitaciones para exportación (CSV, Excel y PDF)."""
    return _repo.fetch_for_pdf(
        ccaa=ccaa,
        estado=estado,
        q=q,
        tecnologia=tecnologia,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        importe_min=importe_min,
        importe_max=importe_max,
        provincia=provincia,
        procedimiento=procedimiento,
        solo_abiertas=solo_abiertas,
        cierre_desde=cierre_desde,
        cierre_hasta=cierre_hasta,
        limit=limit,
    )


def search_for_ask(
    question: str,
    top_k: int,
    ccaa: str | Sequence[str] | None = None,
    tecnologia: str | Sequence[str] | None = None,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    interpretar: bool = True,
    *,
    semantica: bool = False,
) -> list[dict[str, Any]]:
    """Los expedientes de contexto de una pregunta de ``/ask`` sobre el corpus.

    Responde la búsqueda del Investigador (:func:`services.investigador.busqueda.buscar`),
    la misma que pinta la lista de ``/search/semantic``: el asistente se apoya
    en los expedientes que la pantalla enseña, con los filtros que diga la
    propia pregunta. ``semantica`` es la flag ``busqueda_semantica`` de quien
    pregunta (:func:`services.investigador.busqueda.semantica_activa`): con
    ella, la lista del texto se completa con lo que se parece por significado,
    igual que en la pantalla.

    Hasta 2026-11 había un segundo camino: con ``RAG_HYBRID_ENABLED`` la fusión
    **sustituía** al texto —sin los filtros de la frase— y, si el texto fallaba,
    respondía la tsquery estricta con un ``LIKE`` sin orden. Una flag para la
    lista y otra para el asistente dejaban que se contradijeran.

    Un fallo de la base se propaga: ``/ask`` lo distingue de «no hay
    expedientes que respondan» (``api.routes.ask._RecuperacionFallida``).
    """
    from services.investigador.busqueda import buscar, documentos_de_contexto, preparar

    consulta, ambito = preparar(
        question,
        ccaa=_lista(ccaa),
        tecnologia=_lista(tecnologia),
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        interpretar_filtros=interpretar,
    )
    resultado = buscar(consulta, ambito, top_k, semantica=semantica)
    return documentos_de_contexto(resultado.hits, consulta)


def _lista(valor: str | Sequence[str] | None) -> list[str]:
    """Un filtro multi-valor como lista, llegue como CSV, lista o ``None``."""
    if valor is None:
        return []
    if isinstance(valor, str):
        return [v.strip() for v in valor.split(",") if v.strip()]
    return [v for v in valor if v]
