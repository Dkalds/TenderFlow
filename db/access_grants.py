"""Persistencia de concesiones dinámicas de acceso OAuth."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypedDict, cast

from db.database import connect, connect_read

AccessGrantKind = Literal["email", "domain"]


class AccessGrant(TypedDict):
    id: int
    kind: AccessGrantKind
    value: str
    active: bool
    granted_by: int | None
    created_at: str
    updated_at: str
    revoked_at: str | None


class GrantedAccessRequest(TypedDict):
    grant: AccessGrant
    email: str
    empresa: str | None
    previous_state: str


def normalize_grant(kind: AccessGrantKind, value: str) -> str:
    normalized = value.strip().lower()
    if kind == "domain":
        normalized = normalized.removeprefix("@")
    if not normalized or (kind == "email" and "@" not in normalized):
        raise ValueError("Concesión de acceso inválida")
    if kind == "domain" and ("@" in normalized or "." not in normalized):
        raise ValueError("Dominio de acceso inválido")
    return normalized


def is_access_granted(email: str) -> bool:
    normalized = email.strip().lower()
    domain = normalized.rpartition("@")[2]
    if not domain:
        return False
    with connect_read() as connection:
        row = connection.execute(
            "SELECT 1 FROM access_grants "
            "WHERE active = TRUE AND ((kind = 'email' AND value = %s) "
            "OR (kind = 'domain' AND value = %s)) LIMIT 1",
            (normalized, domain),
        ).fetchone()
    return row is not None


def grant_access(
    kind: AccessGrantKind,
    value: str,
    *,
    granted_by: int | None,
) -> AccessGrant:
    normalized = normalize_grant(kind, value)
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO access_grants (kind, value, active, granted_by) "
            "VALUES (%s, %s, TRUE, %s) "
            "ON CONFLICT(kind, value) DO UPDATE SET "
            "active = TRUE, granted_by = excluded.granted_by, "
            "updated_at = NOW(), revoked_at = NULL "
            "RETURNING id, kind, value, active, granted_by, created_at, updated_at, revoked_at",
            (kind, normalized, granted_by),
        )
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("No se pudo persistir la concesión")
    return _row_to_grant(row)


def grant_access_request(
    solicitud_id: int,
    kind: AccessGrantKind,
    *,
    granted_by: int | None,
) -> GrantedAccessRequest | None:
    """Concede y marca la solicitud atendida en una única transacción."""
    with connect() as connection:
        request_row = connection.execute(
            "SELECT email, empresa, estado FROM solicitudes_acceso WHERE id = %s FOR UPDATE",
            (solicitud_id,),
        ).fetchone()
        if request_row is None:
            return None
        email = str(request_row[0]).strip().lower()
        empresa = str(request_row[1]) if request_row[1] else None
        previous_state = str(request_row[2])
        value = normalize_grant(kind, email if kind == "email" else email.rpartition("@")[2])
        grant_row = connection.execute(
            "INSERT INTO access_grants (kind, value, active, granted_by) "
            "VALUES (%s, %s, TRUE, %s) "
            "ON CONFLICT(kind, value) DO UPDATE SET "
            "active = TRUE, granted_by = excluded.granted_by, "
            "updated_at = NOW(), revoked_at = NULL "
            "RETURNING id, kind, value, active, granted_by, created_at, updated_at, revoked_at",
            (kind, value, granted_by),
        ).fetchone()
        if grant_row is None:
            raise RuntimeError("No se pudo persistir la concesión")
        connection.execute(
            "UPDATE solicitudes_acceso SET estado = 'atendida' WHERE id = %s",
            (solicitud_id,),
        )
    return GrantedAccessRequest(
        grant=_row_to_grant(grant_row),
        email=email,
        empresa=empresa,
        previous_state=previous_state,
    )


def revoke_access(grant_id: int) -> AccessGrant | None:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE access_grants SET active = FALSE, revoked_at = NOW(), updated_at = NOW() "
            "WHERE id = %s AND active = TRUE "
            "RETURNING id, kind, value, active, granted_by, created_at, updated_at, revoked_at",
            (grant_id,),
        )
        row = cursor.fetchone()
    return _row_to_grant(row) if row is not None else None


def list_access_grants(*, include_inactive: bool = False) -> list[AccessGrant]:
    where = "" if include_inactive else "WHERE active = TRUE"
    with connect_read() as connection:
        rows = connection.execute(
            "SELECT id, kind, value, active, granted_by, created_at, updated_at, revoked_at "
            f"FROM access_grants {where} ORDER BY active DESC, updated_at DESC, id DESC"
        ).fetchall()
    return [_row_to_grant(row) for row in rows]


def _row_to_grant(row: Sequence[object]) -> AccessGrant:
    return AccessGrant(
        id=int(cast("int", row[0])),
        kind=cast("AccessGrantKind", row[1]),
        value=str(row[2]),
        active=bool(row[3]),
        granted_by=int(cast("int", row[4])) if row[4] is not None else None,
        created_at=str(row[5]),
        updated_at=str(row[6]),
        revoked_at=str(row[7]) if row[7] is not None else None,
    )
