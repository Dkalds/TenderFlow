"""Framework de conectores multi-fuente (ADR-009).

Cada fuente implementa el contrato ``Connector`` (fetch + parse); el runner
genérico aporta cursores incrementales, upsert idempotente con historial,
DLQ, resolución de empresas e invalidación de caché.
"""

from scraper.connectors.base import Connector, ParsedTender, RawNotice, run_connector

__all__ = ["Connector", "ParsedTender", "RawNotice", "run_connector"]
