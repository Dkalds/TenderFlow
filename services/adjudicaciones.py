"""Servicio de adjudicaciones — acceso de lectura enriquecido.

Centraliza la lógica de carga de adjudicaciones. Delega en
``db/repositories/adjudicaciones.py`` para queries SQL.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from db.repositories.adjudicaciones import AdjudicacionRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = AdjudicacionRepository()


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
    """Carga adjudicaciones raw con datos de la licitación asociada."""
    return _repo.load_raw_with_licitaciones(limit=limit, ccaa_filter=ccaa_filter)


def load_licitadores(
    ccaa_filter: tuple[str, ...] | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    """Carga adjudicaciones con datos para el ranking de licitadores."""
    return _repo.load_licitadores(ccaa_filter=ccaa_filter, limit=limit)
