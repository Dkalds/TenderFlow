"""Aislamiento, compartición y compatibilidad legacy del scope organizativo."""

from __future__ import annotations

import pytest

from db.repositories.organizations import OrganizationRepository
from db.repositories.watchlist import WatchlistRepository
from db.saved_filters import list_saved_filters, save_filter
from services.organizations import (
    OrganizationAccessError,
    claim_legacy_scope,
    list_members,
)


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(email=email, password_hash="test-hash")  # pragma: allowlist secret


def test_organization_visibility_shares_only_explicit_items(tmp_db):
    db_mod, _ = tmp_db
    owner = _user("scope-owner@example.test")
    member = _user("scope-member@example.test")
    outsider = _user("scope-outsider@example.test")
    organizations = OrganizationRepository()
    organization_id = int(organizations.create_organization("Scope team", owner)["id"])
    organizations.add_membership(organization_id, member, "member")
    with db_mod.connect() as conn:
        for external_id in ("SCOPE-SHARED", "SCOPE-PRIVATE"):
            conn.execute(
                "INSERT INTO licitaciones (id_externo, titulo, fecha_extraccion) VALUES (?, ?, ?)",
                (external_id, external_id, "2026-07-30T10:00:00+00:00"),
            )

    repo = WatchlistRepository()
    repo.add_item(
        "owner-key",
        owner,
        "SCOPE-SHARED",
        organization_id,
        "organization",
    )
    repo.add_item(
        "owner-key",
        owner,
        "SCOPE-PRIVATE",
        organization_id,
        "private",
    )

    member_items = repo.list_items("member-key", organization_id, member)
    assert [item["id_externo"] for item in member_items] == ["SCOPE-SHARED"]
    owner_items = repo.list_items("owner-key", organization_id, owner)
    assert {item["id_externo"] for item in owner_items} == {
        "SCOPE-SHARED",
        "SCOPE-PRIVATE",
    }
    with pytest.raises(OrganizationAccessError):
        list_members(outsider, organization_id)


def test_legacy_rows_are_claimed_by_personal_organization(tmp_db):
    _db_mod, _ = tmp_db
    user_id = _user("legacy-scope@example.test")
    save_filter("legacy-key", "Filtro", '{"q":"sap"}')

    claim_legacy_scope(user_id, "legacy-key")
    personal_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    rows = list_saved_filters("legacy-key", personal_id)

    assert len(rows) == 1
    assert rows[0]["organization_id"] == personal_id
    assert rows[0]["visibility"] == "private"
