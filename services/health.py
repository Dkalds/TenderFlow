"""Servicio de health check — conectividad de la base de datos."""

from __future__ import annotations

from db.database import connect


def check_db() -> str:
    """Ejecuta ``SELECT 1`` y devuelve ``'ok'`` o ``'error'``."""
    try:
        with connect() as c:
            c.execute("SELECT 1").fetchone()
        return "ok"
    except Exception:
        return "error"
