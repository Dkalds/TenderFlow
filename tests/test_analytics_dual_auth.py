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


def test_source_freshness_responde_con_clave_de_analytics(client, api_db):
    """El panel de Ops la sondea cada 5 min: forma del informe por fuente."""
    token = _owned_key("analytics:read", suffix="freshness-ok")

    response = client.get("/api/v1/analytics/source-freshness", headers={"X-API-Key": token})

    assert response.status_code == 200, response.text
    cuerpo = response.json()
    assert cuerpo["total_sources"] == len(cuerpo["sources"])
    assert 0 <= cuerpo["healthy_sources"] <= cuerpo["total_sources"]
    assert cuerpo["generated_at"]


def test_source_freshness_rechaza_clave_sin_scope_de_analytics(client, api_db):
    token = _owned_key("data:read", suffix="freshness-denied")

    response = client.get("/api/v1/analytics/source-freshness", headers={"X-API-Key": token})

    assert response.status_code == 403, response.text


def test_trends_cpv_responde_con_clave_de_analytics(client, api_db):
    """Sin corpus no hay series, pero la forma del contrato se mantiene."""
    token = _owned_key("analytics:read", suffix="trends-cpv-ok")

    response = client.get(
        "/api/v1/analytics/trends-cpv",
        params={"top_n": 5},
        headers={"X-API-Key": token},
    )

    assert response.status_code == 200, response.text
    cuerpo = response.json()
    assert set(cuerpo) >= {"series_by_cpv", "top_cpv_by_importe", "summary"}
    assert len(cuerpo["series_by_cpv"]) <= 5


def test_trends_cpv_rechaza_clave_sin_scope_de_analytics(client, api_db):
    token = _owned_key("data:read", suffix="trends-cpv-denied")

    response = client.get("/api/v1/analytics/trends-cpv", headers={"X-API-Key": token})

    assert response.status_code == 403, response.text


def test_analytics_rejects_api_key_without_analytics_scope(client, api_db):
    token = _owned_key("data:read", suffix="denied")

    response = client.get(
        "/api/v1/analytics/quality",
        headers={"X-API-Key": token},
    )

    assert response.status_code == 403, response.text
