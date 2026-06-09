"""Servicio de adjudicaciones — acceso de lectura enriquecido.

Centraliza la lógica de carga de adjudicaciones. Delega en
``db/repositories/adjudicaciones.py`` para queries SQL.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger
from services._data_cache import SignalAwareCache

log = get_logger(__name__)

_repo = AdjudicacionRepository()

# Caché del caso sin filtros (el que usa la capa de analytics). Invalidada por
# TTL o por la señal de ingesta.
_raw_adj_cache: SignalAwareCache[list[dict[str, Any]]] = SignalAwareCache()


def load_adjudicaciones(
    *,
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Carga adjudicaciones enriquecidas."""
    from dashboard.data_loader import load_adjudicaciones as _dl_adj

    return _dl_adj(limit=limit, ccaa_filter=ccaa_filter)


def load_raw_adjudicaciones(
    *,
    limit: int | None = None,
    ccaa_filter: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Carga adjudicaciones raw con datos de la licitación asociada.

    El caso sin filtros (usado por la capa de analytics) se cachea en memoria
    con invalidación por TTL + señal de ingesta. Usar :func:`clear_raw_adj_cache`
    para forzar recarga.
    """
    if limit is None and ccaa_filter is None:
        return _raw_adj_cache.get(_repo.load_raw_with_licitaciones)
    return _repo.load_raw_with_licitaciones(limit=limit, ccaa_filter=ccaa_filter)


def clear_raw_adj_cache() -> None:
    """Invalida la caché de :func:`load_raw_adjudicaciones` (caso sin filtros)."""
    _raw_adj_cache.clear()


def load_licitadores(
    ccaa_filter: tuple[str, ...] | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Carga adjudicaciones con datos para el ranking de licitadores."""
    return _repo.load_licitadores(ccaa_filter=ccaa_filter, limit=limit)
