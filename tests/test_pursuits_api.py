"""Contrato HTTP de la primera vertical de pursuits."""

from __future__ import annotations

from api.routes.dual_auth import require_any_auth
from db.repositories.organizations import OrganizationRepository


def _seed(api_db) -> tuple[int, int]:
    from db.database import connect
    from db.users import create_user

    user_id = create_user(
        email="api-pursuits@example.test",
        password_hash="test-hash",  # pragma: allowlist secret
        display_name="API User",
    )
    organization_id = int(OrganizationRepository().ensure_personal_organization(user_id)["id"])
    with connect() as conn:
        conn.execute(
            "INSERT INTO licitaciones "
            "(id_externo, titulo, fecha_limite, fecha_extraccion) VALUES (%s, %s, %s, %s)",
            (
                "LIC-API-PURSUIT",
                "Migración SAP",
                "2026-11-01T10:00:00+00:00",
                "2026-07-30T10:00:00+00:00",
            ),
        )
    return user_id, organization_id


def test_pursuits_api_create_list_detail_and_metrics(client, api_db):
    from api.app import app

    user_id, organization_id = _seed(api_db)
    app.dependency_overrides[require_any_auth] = lambda: {
        "user_id": user_id,
        "auth_method": "session",
        "user_key": "pursuits-test",
    }
    try:
        created = client.post(
            "/api/v1/pursuits",
            json={
                "licitacion_id": "LIC-API-PURSUIT",
                "organization_id": organization_id,
            },
            headers={"X-Idempotency-Key": "create-1"},
        )
        assert created.status_code == 201
        pursuit_id = created.json()["id"]

        duplicate = client.post(
            "/api/v1/pursuits",
            json={
                "licitacion_id": "LIC-API-PURSUIT",
                "organization_id": organization_id,
            },
            headers={"X-Idempotency-Key": "create-1"},
        )
        assert duplicate.status_code == 201
        assert duplicate.json()["id"] == pursuit_id

        listed = client.get(
            "/api/v1/pursuits",
            params={"organization_id": organization_id},
        )
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        detail = client.get(
            f"/api/v1/pursuits/{pursuit_id}",
            params={"organization_id": organization_id},
        )
        assert detail.status_code == 200
        assert len(detail.json()["events"]) == 1

        metrics = client.get(
            "/api/v1/pursuits/metrics",
            params={"organization_id": organization_id},
        )
        assert metrics.status_code == 200
        assert metrics.json()["pursuits_identified"] == 1
    finally:
        app.dependency_overrides.pop(require_any_auth, None)
