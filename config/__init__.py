"""Configuración global del proyecto.

Re-exporta todos los símbolos públicos para compatibilidad con consumidores
que importan directamente desde ``config``:

    from config import settings, SAP_KEYWORDS, PLACE_BASE_URL, ...

Estructura interna:
  - ``config.settings``   — clase Settings, singleton, ensure_data_dirs()
  - ``config.keywords``   — SAP_KEYWORDS, TECHNOLOGY_KEYWORDS
  - ``config.constants``  — URLs, CPV_PREFIXES_TI, HISTORY_TRACKED_FIELDS
"""

from __future__ import annotations

from config.constants import (
    CPV_PREFIXES_TI,
    HISTORY_TRACKED_FIELDS,
    PLACE_BASE_URL,
    PLACE_LIVE_ATOM_URL,
    PLACE_SEARCH_URL,
    PLACE_SYNDICATION_BASE,
    USER_AGENT,
)
from config.keywords import SAP_KEYWORDS, TECHNOLOGY_KEYWORDS
from config.settings import _ROOT, Settings, ensure_data_dirs, settings

__all__ = [
    "CPV_PREFIXES_TI",
    "HISTORY_TRACKED_FIELDS",
    "PLACE_BASE_URL",
    "PLACE_LIVE_ATOM_URL",
    "PLACE_SEARCH_URL",
    "PLACE_SYNDICATION_BASE",
    "SAP_KEYWORDS",
    "TECHNOLOGY_KEYWORDS",
    "USER_AGENT",
    "_ROOT",
    "Settings",
    "ensure_data_dirs",
    "settings",
]
