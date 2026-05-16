"""Capa de repositorios compartida.

Consumida tanto por la API REST como por el dashboard Streamlit.
Centraliza el SQL y expone interfaces tipadas.
"""

from db.repositories.adjudicaciones import AdjudicacionRepository
from db.repositories.api_keys import ApiKeyRepository
from db.repositories.feedback import FeedbackRepository
from db.repositories.licitaciones import LicitacionRepository
from db.repositories.webhooks import WebhookRepository

__all__ = [
    "AdjudicacionRepository",
    "ApiKeyRepository",
    "FeedbackRepository",
    "LicitacionRepository",
    "WebhookRepository",
]
