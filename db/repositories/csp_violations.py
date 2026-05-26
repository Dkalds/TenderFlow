"""Repository para csp_violations."""

from __future__ import annotations

from db.database import connect, now_utc_iso
from observability.logging import get_logger

log = get_logger(__name__)


class CspViolationRepository:
    """Acceso a la tabla ``csp_violations``."""

    def store(
        self,
        *,
        blocked_uri: str,
        violated_directive: str,
        document_uri: str,
        source_file: str,
    ) -> None:
        """Persiste una violación CSP (si la tabla existe)."""
        try:
            now = now_utc_iso()
            with connect() as c:
                tables = {
                    r[0]
                    for r in c.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "csp_violations" in tables:
                    c.execute(
                        "INSERT INTO csp_violations "
                        "(blocked_uri, violated_directive, document_uri, source_file, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (blocked_uri, violated_directive, document_uri, source_file, now),
                    )
        except Exception as exc:
            log.debug("csp_violation_persist_failed", error=str(exc))
