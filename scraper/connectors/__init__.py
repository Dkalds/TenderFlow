"""Framework de conectores multi-fuente (ADR-009).

Cada fuente implementa el contrato ``Connector`` (fetch + parse); el runner
genérico aporta cursores incrementales, upsert idempotente con historial,
DLQ, resolución de empresas e invalidación de caché.

El inventario de fuentes (``REGISTERED_SOURCES``, su frescura y la cobertura
declarada, ``FUERA_DE_ALCANCE``) vive en :mod:`shared.fuentes` y se reexporta
aquí: son datos puros que leen también la API y ``services/``, que no importan
del paquete de ingesta.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from scraper.connectors.base import Connector, ParsedTender, RawNotice, run_connector
from shared.fuentes import (
    FUERA_DE_ALCANCE,
    REGISTERED_SOURCES,
    REGISTERED_SOURCES_BY_ID,
    VIA_DE_ENTRADA_FUERA_DE_ALCANCE,
    AmbitoExcluido,
    EstadoCobertura,
    RegisteredSource,
)

if TYPE_CHECKING:
    from scraper.connectors.euskadi import EuskadiRssConnector
    from scraper.connectors.galicia import GaliciaRssConnector
    from scraper.connectors.watched_company_awards import PlacspWatchedCompanyAwardsConnector

#: Conectores re-exportados en diferido (PEP 562). Importarlos aquí arriba
#: arrastraba ``lxml`` —vía ``regional_rss`` y ``atom_live``— a cualquiera que
#: solo quisiera el inventario, y ``GET /publico/cobertura`` es justo eso: la
#: imagen de la API no instala ``lxml`` (C3.1) y respondía 500.
_CONECTORES_DIFERIDOS = {
    "EuskadiRssConnector": "scraper.connectors.euskadi",
    "GaliciaRssConnector": "scraper.connectors.galicia",
    "PlacspWatchedCompanyAwardsConnector": "scraper.connectors.watched_company_awards",
}


def __getattr__(nombre: str) -> Any:
    modulo = _CONECTORES_DIFERIDOS.get(nombre)
    if modulo is None:
        raise AttributeError(f"module {__name__!r} has no attribute {nombre!r}")
    return getattr(importlib.import_module(modulo), nombre)


__all__ = [
    "FUERA_DE_ALCANCE",
    "REGISTERED_SOURCES",
    "REGISTERED_SOURCES_BY_ID",
    "VIA_DE_ENTRADA_FUERA_DE_ALCANCE",
    "AmbitoExcluido",
    "Connector",
    "EstadoCobertura",
    "EuskadiRssConnector",
    "GaliciaRssConnector",
    "ParsedTender",
    "PlacspWatchedCompanyAwardsConnector",
    "RawNotice",
    "RegisteredSource",
    "run_connector",
]
