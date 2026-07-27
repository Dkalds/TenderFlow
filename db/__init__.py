"""Paquete db — capa de persistencia SQLite/Postgres.

Re-exports de conveniencia para los consumers más frecuentes.
"""

from __future__ import annotations

from db.database import connect, connect_read, init_db, now_utc_iso

__all__ = [
    "connect",
    "connect_read",
    "init_db",
    "now_utc_iso",
]
