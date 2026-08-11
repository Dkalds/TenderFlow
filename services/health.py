"""Servicio de health check — conectividad de la base de datos."""

from __future__ import annotations

from db.database import ping


def check_db() -> str:
    """Devuelve ``'ok'`` si la BD responde, ``'error'`` si no.

    El ``SELECT 1`` vive en ``db.connection.ping`` (ADR-022): aquí solo se
    traduce el booleano al vocabulario que espera el DTO de ``/health``.
    """
    return "ok" if ping() else "error"
