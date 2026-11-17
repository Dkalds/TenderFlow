"""Concesiones de acceso para los tests, por el mismo camino que Administración.

En producción una concesión solo nace al atender una solicitud
(``db.access_grants.grant_access_request``, con su auditoría en la misma
transacción, ADR-039). Los tests que solo necesitan a alguien dentro de la
allowlist la piden aquí: se registra una solicitud y se atiende.

Necesita Postgres (``tmp_db``/``api_db``).
"""

from __future__ import annotations

from uuid import uuid4

from db.access_grants import AccessGrant, AccessGrantKind


def conceder(kind: AccessGrantKind, value: str, *, granted_by: int | None = None) -> AccessGrant:
    """Concede ``value`` (un correo, o un dominio) y devuelve la concesión."""
    from db.access_grants import grant_access_request
    from db.solicitudes_acceso import crear_solicitud

    # Para un dominio, la solicitud la manda alguien de ese dominio.
    email = value if kind == "email" else f"solicitante-{uuid4().hex[:12]}@{value}"
    solicitud_id = crear_solicitud(email=email, empresa=None, mensaje=None, origen="tests")
    concedida = grant_access_request(solicitud_id, kind, granted_by=granted_by)
    assert concedida is not None
    return concedida["grant"]
