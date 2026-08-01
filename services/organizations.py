"""Autorización de organizaciones independiente del frontend."""

from __future__ import annotations

from db.repositories.organizations import OrganizationRepository
from db.users import get_active_user_by_email_ci
from shared.dto import (
    OrganizationMembershipOut,
    OrganizationMembershipUpsert,
    OrganizationSummary,
)

_repo = OrganizationRepository()


class OrganizationAccessError(PermissionError):
    """El usuario no es miembro activo de la organización."""


class OrganizationPermissionError(PermissionError):
    """La membresía existe, pero su rol no permite la operación."""


class OrganizationMemberNotFoundError(LookupError):
    """No existe una cuenta activa con el correo indicado."""


def resolve_organization(
    user_id: int,
    organization_id: int | None,
    *,
    write: bool = False,
) -> tuple[int, str]:
    """Resuelve organización explícita o personal y valida el rol."""
    if organization_id is None:
        personal = _repo.ensure_personal_organization(user_id)
        return int(personal["id"]), str(personal["role"])

    membership = _repo.get_active_membership(organization_id, user_id)
    if membership is None:
        raise OrganizationAccessError("No perteneces a esta organización.")
    role = str(membership["role"])
    if write and role == "viewer":
        raise OrganizationPermissionError("El rol viewer es de solo lectura.")
    return organization_id, role


def require_active_member(organization_id: int, user_id: int) -> None:
    """Valida que un responsable pertenezca activamente al equipo."""
    if _repo.get_active_membership(organization_id, user_id) is None:
        raise OrganizationAccessError(
            "La persona responsable debe ser miembro activo de la organización."
        )


def list_organizations(user_id: int) -> list[OrganizationSummary]:
    """Lista scopes activos; garantiza que el personal exista."""
    _repo.ensure_personal_organization(user_id)
    return [OrganizationSummary.model_validate(row) for row in _repo.list_for_user(user_id)]


def create_organization(user_id: int, name: str) -> OrganizationSummary:
    return OrganizationSummary.model_validate(_repo.create_organization(name.strip(), user_id))


def get_active_organization(user_id: int, organization_id: int | None) -> OrganizationSummary:
    resolved_id, _ = resolve_organization(user_id, organization_id)
    row = _repo.get_for_user(resolved_id, user_id)
    if row is None:
        raise OrganizationAccessError("No perteneces a esta organización.")
    return OrganizationSummary.model_validate(row)


def list_members(user_id: int, organization_id: int) -> list[OrganizationMembershipOut]:
    resolve_organization(user_id, organization_id)
    return [
        OrganizationMembershipOut.model_validate(row) for row in _repo.list_members(organization_id)
    ]


def _guard_owner_row(organization_id: int, target_user_id: int) -> None:
    """Impide degradar o revocar una fila owner desde este flujo.

    La transferencia de propiedad queda fuera de alcance a propósito; el
    único camino para dejar de ser owner sigue siendo uno no expuesto aquí.
    """
    existing = _repo.get_active_membership(organization_id, target_user_id)
    if existing is not None and str(existing["role"]) == "owner":
        raise OrganizationPermissionError(
            "El owner no puede degradarse ni revocarse desde este flujo."
        )


def upsert_membership(
    user_id: int,
    organization_id: int,
    body: OrganizationMembershipUpsert,
) -> OrganizationMembershipOut:
    _, role = resolve_organization(user_id, organization_id)
    if role not in {"owner", "admin"}:
        raise OrganizationPermissionError("Solo owner o admin puede gestionar miembros.")
    if body.role == "owner" and role != "owner":
        raise OrganizationPermissionError("Solo un owner puede asignar otro owner.")
    _guard_owner_row(organization_id, body.user_id)
    row = _repo.add_membership(
        organization_id,
        body.user_id,
        body.role,
        invited_by_user_id=user_id,
        status=body.status,
    )
    return OrganizationMembershipOut.model_validate(row)


def add_member_by_email(
    user_id: int,
    organization_id: int,
    email: str,
    role: str,
) -> OrganizationMembershipOut:
    """Incorpora a un usuario ya registrado a una organización compartida.

    Solo admite ``admin``, ``member`` o ``viewer`` (ver
    :class:`shared.dto.OrganizationMemberInvite`): asignar ``owner`` por este
    camino queda fuera de alcance a propósito.
    """
    _, acting_role = resolve_organization(user_id, organization_id)
    if acting_role not in {"owner", "admin"}:
        raise OrganizationPermissionError(
            "Solo owner o admin puede gestionar miembros."
        )
    target = get_active_user_by_email_ci(email)
    if target is None:
        raise OrganizationMemberNotFoundError(
            "No existe una cuenta activa con ese correo. "
            "La persona debe registrarse primero."
        )
    _guard_owner_row(organization_id, int(target["id"]))
    row = _repo.add_membership(
        organization_id,
        int(target["id"]),
        role,
        invited_by_user_id=user_id,
        status="active",
    )
    return OrganizationMembershipOut.model_validate(row)


def claim_legacy_scope(user_id: int, user_key: str) -> None:
    _repo.claim_legacy_rows(user_id, user_key)
