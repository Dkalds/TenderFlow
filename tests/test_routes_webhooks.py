"""Tests de los endpoints /api/v1/webhooks (GET, PATCH, DELETE, ping, deliveries).

No se duplican:
- SSRF validation tests (en test_api_improvements.py)
- Scope 403 tests con API key restringida (en test_api_improvements.py)
- Create + Idempotency-Key (en test_ola1_fixes.py)

F13·C3.1 (plan Pliegos+RAG): los endpoints migraron de ``require_scope`` a
``require_any_auth`` + ``is_admin`` (recurso compartido, sin owner por
usuario — ver docstring de api/routes/webhooks.py). Los tests de sesión OAuth
admin/no-admin viven aquí; los de API key restringida (sin scope ``*`` →
``is_admin=False``) siguen en test_api_improvements.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from api.app import app
from api.routes.dual_auth import require_any_auth

# Fixtures client, auth, api_db se heredan de conftest.py

_WEBHOOK_URL = "https://example.com/hook"
_WEBHOOK_BODY = {"name": "hook", "url": _WEBHOOK_URL, "event_types": ["*"]}


def _admin_session():
    return {"user_id": 1, "email": "admin@test.com", "is_admin": True, "auth_method": "session"}


def _non_admin_session():
    return {"user_id": 2, "email": "user@test.com", "is_admin": False, "auth_method": "session"}


@pytest.fixture(autouse=True)
def _admin_principal():
    """Las pruebas generales de webhooks se ejecutan como administrador explÃ­cito."""
    app.dependency_overrides[require_any_auth] = _admin_session
    yield
    app.dependency_overrides.clear()


def _create_webhook(client, auth, monkeypatch, *, name="hook", url=_WEBHOOK_URL):
    """Helper: crea un webhook saltándose la validación SSRF y devuelve el JSON de respuesta."""
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    r = client.post(
        "/api/v1/webhooks",
        json={"name": name, "url": url, "event_types": ["*"]},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# GET /{id}
# ---------------------------------------------------------------------------


def test_webhook_get_by_id(client, auth, monkeypatch):
    """Crear webhook → GET /{id} devuelve 200 sin el campo 'secret'."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r = client.get(f"/api/v1/webhooks/{wh_id}", headers=auth)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == wh_id
    assert "secret" not in data, "El campo 'secret' no debe exponerse en GET detalle"


def test_webhook_event_types_is_a_list_not_csv_string(client, auth, monkeypatch):
    """Regresión: event_types se guarda como CSV en la tabla pero la API/UI
    (F13·C3.3a, admin webhooks card) esperan una lista — no un string crudo."""
    _create_webhook(client, auth, monkeypatch)

    r_list = client.get("/api/v1/webhooks", headers=auth)
    assert r_list.status_code == 200, r_list.text
    assert isinstance(r_list.json()[0]["event_types"], list)
    assert r_list.json()[0]["event_types"] == ["*"]

    wh_id = r_list.json()[0]["id"]
    r_get = client.get(f"/api/v1/webhooks/{wh_id}", headers=auth)
    assert isinstance(r_get.json()["event_types"], list)

    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    r_multi = client.post(
        "/api/v1/webhooks",
        json={
            "name": "multi-event",
            "url": _WEBHOOK_URL,
            "event_types": ["watchlist_match", "watchlist_rule.matched"],
        },
        headers=auth,
    )
    multi_id = r_multi.json()["id"]
    r_get_multi = client.get(f"/api/v1/webhooks/{multi_id}", headers=auth)
    assert r_get_multi.json()["event_types"] == ["watchlist_match", "watchlist_rule.matched"]


def test_webhook_get_by_id_no_existe(client, auth):
    """GET /99999 → 404."""
    r = client.get("/api/v1/webhooks/99999", headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /{id}
# ---------------------------------------------------------------------------


def test_webhook_patch_nombre(client, auth, monkeypatch):
    """Crear → PATCH con name nuevo → 200 y el nombre queda actualizado."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r = client.patch(
        f"/api/v1/webhooks/{wh_id}",
        json={"name": "hook-renombrado"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "hook-renombrado"


def test_webhook_patch_vacio(client, auth, monkeypatch):
    """PATCH con body vacío {} → 200 (early return del repo, sin cambios)."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r = client.patch(f"/api/v1/webhooks/{wh_id}", json={}, headers=auth)
    assert r.status_code == 200, r.text


def test_webhook_patch_no_existe(client, auth):
    """PATCH /99999 → 404."""
    r = client.patch("/api/v1/webhooks/99999", json={"name": "x"}, headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /{id}
# ---------------------------------------------------------------------------


def test_webhook_delete(client, auth, monkeypatch):
    """Crear → DELETE → 204, GET posterior → 404."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r_del = client.delete(f"/api/v1/webhooks/{wh_id}", headers=auth)
    assert r_del.status_code == 204

    r_get = client.get(f"/api/v1/webhooks/{wh_id}", headers=auth)
    assert r_get.status_code == 404


def test_webhook_delete_no_existe(client, auth):
    """DELETE /99999 → 404."""
    r = client.delete("/api/v1/webhooks/99999", headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /{id}/ping
# ---------------------------------------------------------------------------


def test_webhook_ping_exitoso(client, auth, monkeypatch):
    """Crear → ping con mock requests.post devolviendo 200 → success=True."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    # Evitar resolución DNS real en el momento del ping
    monkeypatch.setattr("api.routes.webhooks._validate_webhook_url", lambda url: url)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    with patch("api.routes.webhooks._post_pinned_webhook", return_value=mock_resp.status_code):
        r = client.post(f"/api/v1/webhooks/{wh_id}/ping", headers=auth)

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["success"] is True


def test_webhook_ping_no_existe(client, auth):
    """ping /99999 → 404."""
    r = client.post("/api/v1/webhooks/99999/ping", headers=auth)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /{id}/deliveries
# ---------------------------------------------------------------------------


def test_webhook_deliveries_vacias(client, auth, monkeypatch):
    """Crear → GET deliveries → 200, lista vacía (aún no hubo ping)."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    r = client.get(f"/api/v1/webhooks/{wh_id}/deliveries", headers=auth)
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_webhook_deliveries_tras_ping(client, auth, monkeypatch):
    """Crear → ping → GET deliveries → lista con 1 entrada de tipo 'ping'."""
    created = _create_webhook(client, auth, monkeypatch)
    wh_id = created["id"]

    monkeypatch.setattr("api.routes.webhooks._validate_webhook_url", lambda url: url)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    with patch("api.routes.webhooks._post_pinned_webhook", return_value=mock_resp.status_code):
        r_ping = client.post(f"/api/v1/webhooks/{wh_id}/ping", headers=auth)
    assert r_ping.status_code == 200

    r = client.get(f"/api/v1/webhooks/{wh_id}/deliveries", headers=auth)
    assert r.status_code == 200, r.text
    deliveries = r.json()
    assert len(deliveries) == 1
    assert deliveries[0]["event_type"] == "ping"


# ---------------------------------------------------------------------------
# F13·C3.1: require_any_auth + is_admin (sesión OAuth)
# ---------------------------------------------------------------------------


def test_session_non_admin_forbidden(client, api_db):
    """Sesión OAuth sin is_admin → 403 (recurso compartido, no por-usuario)."""
    app.dependency_overrides[require_any_auth] = _non_admin_session
    try:
        resp = client.get("/api/v1/webhooks")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 403


def test_session_admin_can_list(client, api_db):
    """Sesión OAuth con is_admin=True → 200, igual que una API key con scope '*'."""
    app.dependency_overrides[require_any_auth] = _admin_session
    try:
        resp = client.get("/api/v1/webhooks")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json() == []


def test_session_admin_can_create_with_watchlist_rule_matched_event(client, api_db, monkeypatch):
    """F12·C2c: 'watchlist_rule.matched' es un event_type válido al crear."""
    monkeypatch.setattr("api.routes.webhooks.validate_outbound_url", lambda url, **_: url)
    app.dependency_overrides[require_any_auth] = _admin_session
    try:
        resp = client.post(
            "/api/v1/webhooks",
            json={"name": "hook", "url": _WEBHOOK_URL, "event_types": ["watchlist_rule.matched"]},
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201, resp.text


def test_webhook_deliveries_no_existe(client, auth):
    """GET /99999/deliveries → 404."""
    r = client.get("/api/v1/webhooks/99999/deliveries", headers=auth)
    assert r.status_code == 404
