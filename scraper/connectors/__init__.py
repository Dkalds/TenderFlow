"""Framework de conectores multi-fuente (ADR-009).

Cada fuente implementa el contrato ``Connector`` (fetch + parse); el runner
genérico aporta cursores incrementales, upsert idempotente con historial,
DLQ, resolución de empresas e invalidación de caché.
"""

from scraper.connectors.base import Connector, ParsedTender, RawNotice, run_connector
from scraper.connectors.euskadi import EuskadiRssConnector
from scraper.connectors.galicia import GaliciaRssConnector
from scraper.connectors.watched_company_awards import PlacspWatchedCompanyAwardsConnector

__all__ = [
    "Connector",
    "EuskadiRssConnector",
    "GaliciaRssConnector",
    "ParsedTender",
    "PlacspWatchedCompanyAwardsConnector",
    "RawNotice",
    "run_connector",
]
