"""Contrato de autenticación por API key de la superficie Analytics."""

from __future__ import annotations

from api.auth import create_api_key
from db.users import create_user
from shared.auth_core import hash_password


def _owned_key(scopes: str, *, suffix: str) -> str:
    user_id = create_user(
        email=f"analytics-{suffix}@example.test",
        password_hash=hash_password("Analytics-2026-Seguro"),  # pragma: allowlist secret
    )
    return create_api_key(
        f"analytics-{suffix}",
        scopes=scopes,
        user_id=user_id,
    )


def test_analytics_accepts_owned_api_key_with_analytics_scope(client, api_db):
    token = _owned_key("analytics:read", suffix="allowed")

    response = client.get(
        "/api/v1/analytics/quality",
        headers={"X-API-Key": token},
    )

    assert response.status_code == 200, response.text


def test_analytics_rejects_api_key_without_analytics_scope(client, api_db):
    token = _owned_key("data:read", suffix="denied")

    response = client.get(
        "/api/v1/analytics/quality",
        headers={"X-API-Key": token},
    )

    assert response.status_code == 403, response.text
