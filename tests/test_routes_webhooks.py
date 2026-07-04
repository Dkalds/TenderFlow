"""Tests de los endpoints /api/v1/webhooks (GET, PATCH, DELETE, ping, deliveries).

No se duplican:
- SSRF validation tests (en test_api_improvements.py)
- Scope 403 tests (en test_api_improvements.py)
- Create + Idempotency-Key (en test_ola1_fixes.py)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# Fixtures client, auth, api_db se heredan de conftest.py

_WEBHOOK_URL = "https://example.com/hook"
_WEBHOOK_BODY = {"name": "hook", "url": _WEBHOOK_URL, "event_types": ["*"]}


def _create_webhook(client, auth, monkeypatch, *, name="hook", url=_WEBHOOK_URL):
    """Helper: crea un webhook saltándose la validación SSRF y devuelve el JSON de respuesta."""
    monkeypatch.setattr("api.routes.webhooks._is_ssrf_url", lambda u: False)
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
    monkeypatch.setattr("api.routes.webhooks._resolve_and_validate", lambda url: url)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    with patch("requests.post", return_value=mock_resp):
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

    monkeypatch.setattr("api.routes.webhooks._resolve_and_validate", lambda url: url)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "ok"

    with patch("requests.post", return_value=mock_resp):
        r_ping = client.post(f"/api/v1/webhooks/{wh_id}/ping", headers=auth)
    assert r_ping.status_code == 200

    r = client.get(f"/api/v1/webhooks/{wh_id}/deliveries", headers=auth)
    assert r.status_code == 200, r.text
    deliveries = r.json()
    assert len(deliveries) == 1
    assert deliveries[0]["event_type"] == "ping"


def test_webhook_deliveries_no_existe(client, auth):
    """GET /99999/deliveries → 404."""
    r = client.get("/api/v1/webhooks/99999/deliveries", headers=auth)
    assert r.status_code == 404
