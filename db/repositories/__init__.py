"""Capa de repositorios compartida.

Consumida por la API REST y otros servicios de aplicación.
Centraliza el SQL y expone interfaces tipadas.
"""

from db.repositories.adjudicaciones import AdjudicacionRepository
from db.repositories.aggregates import AggregateRepository
from db.repositories.api_keys import ApiKeyRepository
from db.repositories.audit import AuditRepository
from db.repositories.csp_violations import CspViolationRepository
from db.repositories.extraction_runs import ExtractionRunRepository
from db.repositories.feedback import FeedbackRepository
from db.repositories.licitaciones import LicitacionRepository
from db.repositories.predicciones import PrediccionesRepository
from db.repositories.watchlist import WatchlistRepository
from db.repositories.webhooks import WebhookRepository

__all__ = [
    "AdjudicacionRepository",
    "AggregateRepository",
    "ApiKeyRepository",
    "AuditRepository",
    "CspViolationRepository",
    "ExtractionRunRepository",
    "FeedbackRepository",
    "LicitacionRepository",
    "PrediccionesRepository",
    "WatchlistRepository",
    "WebhookRepository",
]
