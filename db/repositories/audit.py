"""Repository para audit_log."""

from __future__ import annotations

from typing import Any

from db.database import connect_read
from db.repositories.base import rows_to_dicts
from observability.logging import get_logger

log = get_logger(__name__)


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
                # Export GDPR: devolver [] ante un fallo entrega al usuario un
                # export incompleto que parece completo.
                log.warning("audit_export_by_user_key_failed", exc_info=True)
                return []
