"""Repository para audit_log."""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts


class AuditRepository:
    """Acceso de lectura a la tabla ``audit_log``."""

    def export_by_user_key(self, user_key: str) -> list[dict[str, Any]]:
        """Exporta el audit log filtrado por ``user_key`` (GDPR)."""
        with connect_read() as c:
            try:
                cur = c.execute(
                    "SELECT * FROM audit_log WHERE user_key = ? "
                    "ORDER BY created_at DESC LIMIT 1000",
                    (user_key,),
                )
                return rows_to_dicts(cur)
            except Exception:
                return []
