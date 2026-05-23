"""Módulo shared — utilidades compartidas entre scraper, scheduler y dashboard.

Re-exports de conveniencia para los consumers más frecuentes.
Los paths largos (``from shared.geo import nuts_to_ccaa``) siguen funcionando.
"""

from __future__ import annotations

# Cache
from shared.cache import get_cache, reset_cache

# DTOs
from shared.dto import (
    ClusterSummary,
    KpiSnapshotDTO,
    LicitacionDetail,
    LicitacionSummary,
    PaginatedResponse,
    WatchlistEntry,
)

# Geo
from shared.geo import NUTS3_TO_CCAA, nuts_to_ccaa

# Types
from shared.types import JsonDict, LicitacionRow, UserRow

__all__ = [
    "NUTS3_TO_CCAA",
    "ClusterSummary",
    "JsonDict",
    "KpiSnapshotDTO",
    "LicitacionDetail",
    "LicitacionRow",
    "LicitacionSummary",
    "PaginatedResponse",
    "UserRow",
    "WatchlistEntry",
    "get_cache",
    "nuts_to_ccaa",
    "reset_cache",
]
