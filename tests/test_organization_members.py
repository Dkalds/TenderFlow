"""Alta de miembros de organización por correo y protección del owner."""

from __future__ import annotations

import pytest

from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository
from services.organizations import (
    OrganizationMemberNotFoundError,
    OrganizationPermissionError,
    add_member_by_email,
    upsert_membership,
)
from shared.dto import OrganizationMembershipUpsert


def _user(email: str, *, display_name: str | None = None) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=display_name,
    )


def test_add_member_by_email_enrolls_existing_active_user(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-email@example.test")
    target = _user("new-member@example.test", display_name="Nueva Persona")
    organizations = OrganizationRepository()
    organization_id = int(organizations.create_organization("Equipo por correo", owner)["id"])

    result = add_member_by_email(owner, organization_id, "New-Member@Example.TEST", "member")

    assert result.user_id == target
    assert result.role == "member"
    assert result.status == "active"
    assert result.display_name == "Nueva Persona"
    assert result.email == "new-member@example.test"


def test_add_member_by_email_rejects_unknown_email(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-unknown@example.test")
    organizations = OrganizationRepository()
    organization_id = int(organizations.create_organization("Equipo sin match", owner)["id"])

    with pytest.raises(OrganizationMemberNotFoundError):
        add_member_by_email(owner, organization_id, "no-existe@example.test", "member")


def test_add_member_by_email_requires_owner_or_admin(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-viewer@example.test")
    viewer = _user("viewer-caller@example.test")
    target = _user("target-viewer-call@example.test")
    organizations = OrganizationRepository()
    organization_id = int(organizations.create_organization("Equipo con viewer", owner)["id"])
    organizations.add_membership(organization_id, viewer, "viewer")

    with pytest.raises(OrganizationPermissionError):
        add_member_by_email(viewer, organization_id, "target-viewer-call@example.test", "member")

    # El objetivo nunca se incorporó: el rechazo ocurrió antes de tocar la BD.
    assert organizations.get_active_membership(organization_id, target) is None


def test_add_member_by_email_cannot_touch_an_existing_owner_row(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-self@example.test")
    organizations = OrganizationRepository()
    organization_id = int(organizations.create_organization("Equipo owner", owner)["id"])

    # El propio owner intenta "re-añadirse" con un rol distinto vía correo.
    with pytest.raises(OrganizationPermissionError):
        add_member_by_email(owner, organization_id, "owner-self@example.test", "admin")


def test_upsert_membership_cannot_demote_owner(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-demote@example.test")
    organizations = OrganizationRepository()
    organization_id = int(organizations.create_organization("Equipo demote", owner)["id"])

    with pytest.raises(OrganizationPermissionError):
        upsert_membership(
            owner,
            organization_id,
            OrganizationMembershipUpsert(user_id=owner, role="member", status="active"),
        )


def test_upsert_membership_can_change_role_of_a_non_owner_member(tmp_db):
    _db_mod, _ = tmp_db
    owner = _user("owner-promote@example.test")
    member = _user("member-promote@example.test")
    organizations = OrganizationRepository()
    organization_id = int(organizations.create_organization("Equipo promote", owner)["id"])
    organizations.add_membership(organization_id, member, "member")

    result = upsert_membership(
        owner,
        organization_id,
        OrganizationMembershipUpsert(user_id=member, role="admin", status="active"),
    )

    assert result.role == "admin"


def _seed_api(api_db) -> tuple[int, int]:
    owner = _user("api-owner@example.com", display_name="Owner API")
    _user("api-invitee@example.com", display_name="Invitada API")
    organizations = OrganizationRepository()
    organization_id = int(organizations.create_organization("Equipo API", owner)["id"])
    return owner, organization_id


def test_post_organization_member_api_contract(client, api_db):
    from api.app import app

    owner, organization_id = _seed_api(api_db)
    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": owner,
        "auth_method": "session",
        "user_key": "org-members-test",
    }
    try:
        created = client.post(
            f"/api/v1/organizations/{organization_id}/members",
            json={"email": "api-invitee@example.com", "role": "member"},
        )
        assert created.status_code == 201
        body = created.json()
        assert body["role"] == "member"
        assert body["email"] == "api-invitee@example.com"
        assert body["display_name"] == "Invitada API"

        not_found = client.post(
            f"/api/v1/organizations/{organization_id}/members",
            json={"email": "sin-cuenta@example.com", "role": "member"},
        )
        assert not_found.status_code == 404

        listed = client.get(f"/api/v1/organizations/{organization_id}/members")
        assert listed.status_code == 200
        emails = {row["email"] for row in listed.json()}
        assert "api-invitee@example.com" in emails
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


def test_post_organization_member_api_forbidden_for_non_admin(client, api_db):
    from api.app import app

    _owner, organization_id = _seed_api(api_db)
    outsider = _user("api-outsider@example.com")
    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": outsider,
        "auth_method": "session",
        "user_key": "org-members-outsider-test",
    }
    try:
        response = client.post(
            f"/api/v1/organizations/{organization_id}/members",
            json={"email": "api-invitee@example.com", "role": "member"},
        )
        assert response.status_code == 403
    finally:
        app.dependency_overrides.pop(require_any_auth, None)
