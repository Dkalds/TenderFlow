"""Aislamiento, compartición y compatibilidad legacy del scope organizativo."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from db.repositories.organizations import OrganizationRepository
from db.repositories.watchlist import WatchlistRepository
from db.saved_filters import list_saved_filters, save_filter
from services.organizations import (
    OrganizationAccessError,
    claim_legacy_scope,
    list_members,
)
from shared.identity import user_key_from_email


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


# ---------------------------------------------------------------------------
# Frontera server-side: organization_id omitido nunca cae a una query sin
# filtro de organización (ver api/tenancy.py y docs/IMPROVEMENT_BACKLOG.md).
# ---------------------------------------------------------------------------


def _session_ctx(user_id: int, email: str) -> dict:
    """Ctx equivalente al que produce ``require_any_auth`` para una sesión."""
    return {
        "user_id": user_id,
        "email": email,
        "display_name": "Test User",
        "is_admin": False,
        "auth_method": "session",
        "authenticated_at": datetime.now(UTC).isoformat(),
        "user_key": user_key_from_email(email, user_id),
    }


@pytest.fixture(autouse=True)
def _clear_dependency_overrides():
    yield
    from api.app import app

    app.dependency_overrides.clear()


def test_omitting_organization_id_scopes_to_personal_not_merged_across_orgs(client, api_db):
    """Regresión del bug de tenencia: antes, omitir organization_id caía a
    ``WHERE user_key = ?`` sin mirar organization_id en absoluto -- un favorito
    guardado bajo el contexto de una organización compartida se filtraba igual
    en la vista "sin organización". Tras el fix, omitirlo resuelve siempre a
    la organización personal -- una vista distinta y separada, no una fusión.
    """
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    owner_id = _user("scope-boundary-owner@example.test")
    ctx = _session_ctx(owner_id, "scope-boundary-owner@example.test")
    app.dependency_overrides[require_any_auth] = lambda: ctx

    organizations = OrganizationRepository()
    shared_org_id = int(organizations.create_organization("Shared team", owner_id)["id"])

    with client:
        resp = client.post(
            "/api/v1/watchlist/items",
            json={
                "id_externo": "SCOPE-SHARED-ITEM",
                "organization_id": shared_org_id,
                "visibility": "organization",
            },
        )
        assert resp.status_code == 201, resp.text

        resp = client.post(
            "/api/v1/watchlist/items",
            json={"id_externo": "SCOPE-PERSONAL-ITEM"},
        )
        assert resp.status_code == 201, resp.text

        resp = client.get("/api/v1/watchlist/items")
        assert resp.status_code == 200, resp.text
        ids = {item["id_externo"] for item in resp.json()["items"]}

    # El ítem creado bajo el contexto de la organización compartida NO debe
    # aparecer en la vista por defecto (personal) -- si apareciera, sería la
    # señal exacta del bug: un GET sin organization_id viendo filas de OTRA
    # organización solo porque las creó el mismo user_key.
    assert "SCOPE-SHARED-ITEM" not in ids


def test_organization_id_without_membership_is_rejected(client, api_db):
    """Pedir explícitamente una organización ajena devuelve 403, no datos."""
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    owner_id = _user("scope-owner-2@example.test")
    outsider_id = _user("scope-outsider-2@example.test")
    organizations = OrganizationRepository()
    org_id = int(organizations.create_organization("Owner-only org", owner_id)["id"])

    outsider_ctx = _session_ctx(outsider_id, "scope-outsider-2@example.test")
    app.dependency_overrides[require_any_auth] = lambda: outsider_ctx

    with client:
        resp = client.get(f"/api/v1/watchlist/items?organization_id={org_id}")
    assert resp.status_code == 403, resp.text


def test_viewer_role_cannot_write(client, api_db):
    """Un miembro con rol viewer recibe 403 al intentar escribir."""
    from api.app import app
    from api.routes.dual_auth import require_any_auth

    owner_id = _user("scope-owner-3@example.test")
    viewer_id = _user("scope-viewer-3@example.test")
    organizations = OrganizationRepository()
    org_id = int(organizations.create_organization("Viewer org", owner_id)["id"])
    organizations.add_membership(org_id, viewer_id, "viewer")

    viewer_ctx = _session_ctx(viewer_id, "scope-viewer-3@example.test")
    app.dependency_overrides[require_any_auth] = lambda: viewer_ctx

    with client:
        resp = client.post(
            "/api/v1/watchlist/items",
            json={"id_externo": "VIEWER-CANNOT-ADD", "organization_id": org_id},
        )
    assert resp.status_code == 403, resp.text
