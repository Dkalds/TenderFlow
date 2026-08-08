"""Contrato HTTP de organizaciones y oportunidades: permisos y códigos de error.

``test_pursuits_api.py`` cubre el camino feliz (crear, listar, detalle,
métricas). Aquí se fija lo que el cliente ve cuando algo va mal: qué error de
dominio se traduce a 403, a 404, a 409 y a 422. Ese mapeo es contrato — el
frontend decide con él si reintenta, si refresca o si muestra un mensaje.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository


def _user(email: str) -> int:
    from db.users import create_user

    return create_user(
        email=email,
        password_hash="test-hash",  # pragma: allowlist secret
        display_name=email.split("@")[0],
    )


def _licitacion(id_externo: str = "LIC-CONTRACT") -> None:
    from db.database import connect

    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (id_externo, "Migración SAP", "2026-11-01T10:00:00+00:00", "2026-07-30T10:00:00+00:00"),
        )


@pytest.fixture()
def as_user(api_db) -> Iterator[object]:
    """Autentica la petición como el ``user_id`` que indique cada test."""
    from api.app import app

    class _Principal:
        user_id: int | None = None

        def __call__(self) -> dict[str, object]:
            return {
                "user_id": self.user_id,
                "auth_method": "session",
                "user_key": f"contract-{self.user_id}",
            }

    principal = _Principal()
    app.dependency_overrides[require_any_auth] = principal
    try:
        yield principal
    finally:
        app.dependency_overrides.pop(require_any_auth, None)


# ── /organizations ───────────────────────────────────────────────────────


def test_listing_organizations_materialises_the_personal_scope(client, as_user):
    as_user.user_id = _user("contract-solo@example.test")

    listed = client.get("/api/v1/organizations")

    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["is_personal"] is True
    assert body[0]["role"] == "owner"


def test_creating_a_shared_organization_makes_the_creator_owner(client, as_user):
    as_user.user_id = _user("contract-founder@example.test")

    created = client.post("/api/v1/organizations", json={"name": "Equipo Bid"})

    assert created.status_code == 201
    assert created.json()["name"] == "Equipo Bid"
    assert created.json()["is_personal"] is False
    assert created.json()["role"] == "owner"


def test_the_active_organization_of_an_outsider_is_forbidden(client, as_user):
    owner = _user("contract-owner@example.test")
    outsider = _user("contract-outsider@example.test")
    organization_id = int(OrganizationRepository().create_organization("Equipo", owner)["id"])

    as_user.user_id = owner
    assert (
        client.get(f"/api/v1/organizations/active?organization_id={organization_id}").status_code
        == 200
    )

    as_user.user_id = outsider
    denied = client.get(f"/api/v1/organizations/active?organization_id={organization_id}")

    assert denied.status_code == 403


def test_members_are_listed_for_a_member_and_denied_for_an_outsider(client, as_user):
    owner = _user("contract-list-owner@example.test")
    member = _user("contract-list-member@example.test")
    outsider = _user("contract-list-outsider@example.test")
    repo = OrganizationRepository()
    organization_id = int(repo.create_organization("Equipo", owner)["id"])
    repo.add_membership(organization_id, member, "member")

    as_user.user_id = member
    listed = client.get(f"/api/v1/organizations/{organization_id}/members")
    assert listed.status_code == 200
    assert {row["user_id"] for row in listed.json()} == {owner, member}

    as_user.user_id = outsider
    assert client.get(f"/api/v1/organizations/{organization_id}/members").status_code == 403


def test_only_owner_or_admin_can_manage_members(client, as_user):
    owner = _user("contract-mgr-owner@example.test")
    member = _user("contract-mgr-member@example.test")
    newcomer = _user("contract-mgr-new@example.test")
    repo = OrganizationRepository()
    organization_id = int(repo.create_organization("Equipo", owner)["id"])
    repo.add_membership(organization_id, member, "member")

    as_user.user_id = member
    denied = client.put(
        f"/api/v1/organizations/{organization_id}/members/{newcomer}",
        json={"user_id": newcomer, "role": "member", "status": "active"},
    )
    assert denied.status_code == 403

    as_user.user_id = owner
    granted = client.put(
        f"/api/v1/organizations/{organization_id}/members/{newcomer}",
        json={"user_id": newcomer, "role": "member", "status": "active"},
    )
    assert granted.status_code == 200
    assert granted.json()["role"] == "member"


def test_only_an_owner_can_appoint_another_owner(client, as_user):
    owner = _user("contract-owner2@example.test")
    admin = _user("contract-admin@example.test")
    newcomer = _user("contract-heir@example.test")
    repo = OrganizationRepository()
    organization_id = int(repo.create_organization("Equipo", owner)["id"])
    repo.add_membership(organization_id, admin, "admin")

    as_user.user_id = admin
    denied = client.put(
        f"/api/v1/organizations/{organization_id}/members/{newcomer}",
        json={"user_id": newcomer, "role": "owner", "status": "active"},
    )

    assert denied.status_code == 403
    assert "owner" in denied.json()["detail"]


def test_a_member_payload_that_contradicts_the_path_is_rejected(client, as_user):
    owner = _user("contract-mismatch@example.test")
    other = _user("contract-mismatch-other@example.test")
    organization_id = int(OrganizationRepository().create_organization("Equipo", owner)["id"])

    as_user.user_id = owner
    mismatched = client.put(
        f"/api/v1/organizations/{organization_id}/members/{other}",
        json={"user_id": other + 1, "role": "member", "status": "active"},
    )

    assert mismatched.status_code == 422


# ── /pursuits: mapeo de errores ──────────────────────────────────────────


def test_opening_a_pursuit_on_an_unknown_tender_is_422(client, as_user):
    as_user.user_id = _user("contract-unknown-tender@example.test")

    created = client.post("/api/v1/pursuits", json={"licitacion_id": "NO-EXISTE"})

    assert created.status_code == 422
    assert "licitación" in created.json()["detail"]


def test_a_viewer_cannot_open_a_pursuit(client, as_user):
    owner = _user("contract-viewer-owner@example.test")
    viewer = _user("contract-viewer@example.test")
    repo = OrganizationRepository()
    organization_id = int(repo.create_organization("Equipo", owner)["id"])
    repo.add_membership(organization_id, viewer, "viewer")
    _licitacion()

    as_user.user_id = viewer
    denied = client.post(
        "/api/v1/pursuits",
        json={"licitacion_id": "LIC-CONTRACT", "organization_id": organization_id},
    )

    assert denied.status_code == 403
    assert "viewer" in denied.json()["detail"]


def test_reading_a_pursuit_of_another_organization_is_403(client, as_user):
    owner = _user("contract-read-owner@example.test")
    outsider = _user("contract-read-outsider@example.test")
    organization_id = int(OrganizationRepository().create_organization("Equipo", owner)["id"])
    _licitacion()

    as_user.user_id = owner
    pursuit_id = client.post(
        "/api/v1/pursuits",
        json={"licitacion_id": "LIC-CONTRACT", "organization_id": organization_id},
    ).json()["id"]

    as_user.user_id = outsider
    for path in (
        f"/api/v1/pursuits/{pursuit_id}?organization_id={organization_id}",
        f"/api/v1/pursuits?organization_id={organization_id}",
        f"/api/v1/pursuits/metrics?organization_id={organization_id}",
    ):
        assert client.get(path).status_code == 403, path


def test_an_unknown_pursuit_is_404(client, as_user):
    as_user.user_id = _user("contract-404@example.test")

    assert client.get("/api/v1/pursuits/424242").status_code == 404
    assert client.patch("/api/v1/pursuits/424242", json={"status": "qualifying"}).status_code == 404


def test_an_illegal_transition_is_409_and_a_broken_rule_is_422(client, as_user):
    as_user.user_id = _user("contract-transitions@example.test")
    _licitacion()

    pursuit_id = client.post("/api/v1/pursuits", json={"licitacion_id": "LIC-CONTRACT"}).json()[
        "id"
    ]

    # Saltarse el workflow es un conflicto de estado, no un payload inválido.
    illegal = client.patch(f"/api/v1/pursuits/{pursuit_id}", json={"status": "submitted"})
    assert illegal.status_code == 409

    assert (
        client.patch(f"/api/v1/pursuits/{pursuit_id}", json={"status": "qualifying"}).status_code
        == 200
    )

    # La transición es legal, la regla de negocio no se cumple.
    unjustified = client.patch(
        f"/api/v1/pursuits/{pursuit_id}",
        json={"status": "go_no_go", "decision": "go"},
    )
    assert unjustified.status_code == 422
    assert "motivo" in unjustified.json()["detail"]


def test_a_stale_expected_version_is_409(client, as_user):
    as_user.user_id = _user("contract-conflict@example.test")
    _licitacion()

    pursuit_id = client.post("/api/v1/pursuits", json={"licitacion_id": "LIC-CONTRACT"}).json()[
        "id"
    ]
    assert (
        client.patch(f"/api/v1/pursuits/{pursuit_id}", json={"status": "qualifying"}).status_code
        == 200
    )

    conflict = client.patch(
        f"/api/v1/pursuits/{pursuit_id}",
        json={
            "status": "go_no_go",
            "decision": "go",
            "decision_reason": "x",
            "expected_version": 1,
        },
    )

    assert conflict.status_code == 409


def test_an_inverted_metrics_period_is_422(client, as_user):
    as_user.user_id = _user("contract-period@example.test")

    inverted = client.get(
        "/api/v1/pursuits/metrics",
        params={"period_from": "2026-07-01T00:00:00Z", "period_to": "2026-06-01T00:00:00Z"},
    )

    assert inverted.status_code == 422


def test_the_metrics_route_is_not_shadowed_by_the_detail_route(client, as_user):
    """``/pursuits/metrics`` debe resolver antes que ``/pursuits/{pursuit_id}``."""
    as_user.user_id = _user("contract-routing@example.test")

    metrics = client.get("/api/v1/pursuits/metrics")

    assert metrics.status_code == 200
    assert metrics.json()["pursuits_identified"] == 0


def test_a_retried_patch_with_the_same_idempotency_key_does_not_advance_the_version(
    client, as_user
):
    as_user.user_id = _user("contract-idempotent@example.test")
    _licitacion()

    pursuit_id = client.post("/api/v1/pursuits", json={"licitacion_id": "LIC-CONTRACT"}).json()[
        "id"
    ]
    headers = {"X-Idempotency-Key": "patch-qualifying-1"}

    first = client.patch(
        f"/api/v1/pursuits/{pursuit_id}", json={"status": "qualifying"}, headers=headers
    )
    retry = client.patch(
        f"/api/v1/pursuits/{pursuit_id}", json={"status": "qualifying"}, headers=headers
    )

    assert first.status_code == retry.status_code == 200
    assert first.json()["version"] == retry.json()["version"]
    assert len(retry.json()["events"]) == 2


def test_listing_pursuits_paginates_and_filters_by_status(client, as_user):
    as_user.user_id = _user("contract-paging@example.test")
    _licitacion("LIC-CONTRACT-A")
    _licitacion("LIC-CONTRACT-B")

    first = client.post("/api/v1/pursuits", json={"licitacion_id": "LIC-CONTRACT-A"}).json()["id"]
    client.post("/api/v1/pursuits", json={"licitacion_id": "LIC-CONTRACT-B"})
    assert (
        client.patch(f"/api/v1/pursuits/{first}", json={"status": "qualifying"}).status_code == 200
    )

    qualifying = client.get("/api/v1/pursuits", params={"status": "qualifying"}).json()
    page = client.get("/api/v1/pursuits", params={"limit": 1, "offset": 1}).json()

    assert qualifying["total"] == 1
    assert qualifying["items"][0]["id"] == first
    assert page["total"] == 2
    assert len(page["items"]) == 1
