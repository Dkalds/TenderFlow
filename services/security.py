"""Servicio de seguridad — persistencia de violaciones CSP."""

from __future__ import annotations

from db.repositories.csp_violations import CspViolationRepository
from observability.logging import get_logger

log = get_logger(__name__)

_repo = CspViolationRepository()


def store_csp_violation(
    blocked_uri: str,
    violated_directive: str,
    document_uri: str,
    source_file: str,
) -> None:
    """Persiste una violación CSP en ``csp_violations`` (si la tabla existe)."""
    _repo.store(
        blocked_uri=blocked_uri,
        violated_directive=violated_directive,
        document_uri=document_uri,
        source_file=source_file,
    )
