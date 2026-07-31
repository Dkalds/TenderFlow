"""Tests basicos para /api/v1/competitive — verifica 200 con BD vacia."""

from __future__ import annotations

import pytest


@pytest.fixture()
def api_key(api_db):
    """Override de conftest: vincula la key a un usuario real.

    ``/competitive/watchlist`` resuelve organización server-side
    (``api/tenancy.py``), que necesita un ``users.id`` real para
    ``ensure_personal_organization``. La key sin vincular del fixture
    compartido usa su propio id como ``user_id`` postizo (compatibilidad
    dev/test de ``api/routes/dual_auth.py``), que no existe en ``users``.
    ``auth`` (conftest.py) depende de ``api_key`` y recoge este override.
    """
    from api.auth import create_api_key
    from db.users import create_user

    user_id = create_user(email="competitive-api@example.test", password_hash="test-hash")
    return create_api_key("test-key", scopes="*", user_id=user_id)


# ---------------------------------------------------------------------------
# Renovaciones
# ---------------------------------------------------------------------------


def test_competitive_renovaciones_vacio(client, auth):
    """GET /competitive/renovaciones → 200 con items vacío."""
    r = client.get("/api/v1/competitive/renovaciones", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert isinstance(data["items"], list)


def test_competitive_renovaciones_resumen_vacio(client, auth):
    """GET /competitive/renovaciones/resumen → 200 con items vacío."""
    r = client.get("/api/v1/competitive/renovaciones/resumen", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert isinstance(data["items"], list)


def test_competitive_renovaciones_resumen_incluye_totales(client, auth):
    """GET /competitive/renovaciones/resumen expone `totales` (server-side, sin
    GROUP BY) para banners que necesitan un par de cifras del dataset completo
    (usado por el banner de Pipeline & Alertas hacia /renovaciones)."""
    r = client.get("/api/v1/competitive/renovaciones/resumen", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "totales" in data
    assert data["totales"]["contratos_venciendo"] == 0
    assert data["totales"]["importe_en_juego"] == 0


# ---------------------------------------------------------------------------
# Bajas
# ---------------------------------------------------------------------------


def test_competitive_bajas_vacio(client, auth):
    """GET /competitive/bajas → 200 (sin datos de adjudicaciones)."""
    r = client.get("/api/v1/competitive/bajas", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert isinstance(data["items"], list)


def test_competitive_bajas_referencia_vacio(client, auth):
    """GET /competitive/bajas/referencia?organo=X&cpv=72 → 200."""
    r = client.get(
        "/api/v1/competitive/bajas/referencia?organo=OrganoX&cpv=72",
        headers=auth,
    )
    assert r.status_code == 200


def test_competitive_bajas_group_by_invalido(client, auth):
    """group_by fuera del patron → 422."""
    r = client.get("/api/v1/competitive/bajas?group_by=INVALIDO", headers=auth)
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Mercado
# ---------------------------------------------------------------------------


def test_competitive_cuota_vacio(client, auth):
    """GET /competitive/cuota → 200 con items vacío."""
    r = client.get("/api/v1/competitive/cuota", headers=auth)
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


def test_competitive_hhi_vacio(client, auth):
    """GET /competitive/hhi → 200 con items vacío."""
    r = client.get("/api/v1/competitive/hhi", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "segment_by" in data


def test_competitive_perfil_no_existe(client, auth):
    """GET /competitive/empresas/99999/perfil → 404 (empresa sin adjudicaciones)."""
    r = client.get("/api/v1/competitive/empresas/99999/perfil", headers=auth)
    assert r.status_code == 404


def test_competitive_adjudicaciones_empresa_vacio(client, auth):
    r = client.get(
        "/api/v1/competitive/empresas/99999/adjudicaciones?sort=importe_desc",
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "limit": 25, "offset": 0}


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------


def test_competitive_watchlist_vacio(client, auth):
    """GET /competitive/watchlist → 200 con lista vacía."""
    r = client.get("/api/v1/competitive/watchlist", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert data["items"] == []


def test_competitive_watchlist_add_empresa_no_existe(client, auth):
    """POST /competitive/watchlist con empresa_id=99999 (no en maestro) → 404."""
    r = client.post(
        "/api/v1/competitive/watchlist",
        json={"empresa_id": 99999, "frequency": "daily"},
        headers=auth,
    )
    assert r.status_code == 404


def test_competitive_watchlist_sin_auth(client):
    """Sin autenticacion → 401 o 403."""
    r = client.get("/api/v1/competitive/watchlist")
    assert r.status_code in (401, 403)
