"""Módulo shared — utilidades compartidas entre scraper, scheduler y dashboard.

Re-exports de conveniencia para los consumers más frecuentes.
Los paths largos (``from shared.geo import nuts_to_ccaa``) siguen funcionando.

Este fichero se encoge cuando algo de ``shared/dto.py`` deja de existir: un
re-export es un consumidor más, y mantenerlo vivo apuntando a nada solo
retrasaría el error hasta el import. El 2026-09-03 se fueron
``ClusterSummary``, ``KpiSnapshotDTO``, ``LicitacionDetail`` y
``LicitacionSummary`` con las clases que nombraban.
"""

from __future__ import annotations

# Cache
from shared.cache import get_cache, reset_cache

# DTOs
from shared.dto import PaginatedResponse, WatchlistEntry

# Geo
from shared.geo import NUTS3_TO_CCAA, nuts_to_ccaa

# Types
from shared.types import JsonDict, LicitacionRow, UserRow

__all__ = [
    "NUTS3_TO_CCAA",
    "JsonDict",
    "LicitacionRow",
    "PaginatedResponse",
    "UserRow",
    "WatchlistEntry",
    "get_cache",
    "nuts_to_ccaa",
    "reset_cache",
]
