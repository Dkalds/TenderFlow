"""Tests para GET/POST/DELETE /api/v1/saved-filters."""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_key(api_db):
    """Override de conftest: vincula la key a un usuario real.

    Esta ruta resuelve organización server-side (``api/tenancy.py``), que
    necesita un ``users.id`` real para ``ensure_personal_organization``. La
    key sin vincular del fixture compartido usa su propio id como
    ``user_id`` postizo (compatibilidad dev/test de
    ``api/routes/dual_auth.py``), que no existe en ``users``. ``auth``
    (conftest.py) depende de ``api_key`` y recoge este override.
    """
    from api.auth import create_api_key
    from db.users import create_user

    user_id = create_user(email="saved-filters-api@example.test", password_hash="test-hash")
    return create_api_key("test-key", scopes="*", user_id=user_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _crear_filtro(client, auth, *, name: str = "Mi filtro", filters_json: str | None = None):
    if filters_json is None:
        filters_json = json.dumps({"estado": "PUB"})
    r = client.post(
        "/api/v1/saved-filters",
        json={"name": name, "filters_json": filters_json},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# GET /saved-filters
# ---------------------------------------------------------------------------


def test_filtros_lista_vacia(client, auth):
    """Sin filtros guardados → {"items": []}."""
    r = client.get("/api/v1/saved-filters", headers=auth)
    assert r.status_code == 200
    assert r.json() == {"items": []}


# ---------------------------------------------------------------------------
# POST /saved-filters
# ---------------------------------------------------------------------------


def test_filtros_crear_y_listar(client, auth):
    """POST crea el filtro → GET devuelve el nombre correcto."""
    _crear_filtro(client, auth, name="Filtro SAP Madrid")

    r = client.get("/api/v1/saved-filters", headers=auth)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Filtro SAP Madrid"


def test_filtros_json_invalido(client, auth):
    """filters_json con string no-JSON → 422."""
    r = client.post(
        "/api/v1/saved-filters",
        json={"name": "Roto", "filters_json": "no-es-json"},
        headers=auth,
    )
    assert r.status_code == 422


def test_filtros_nombre_vacio(client, auth):
    """name="" (min_length=1) → 422."""
    r = client.post(
        "/api/v1/saved-filters",
        json={"name": "", "filters_json": "{}"},
        headers=auth,
    )
    assert r.status_code == 422


def test_filtros_multiples_crear(client, auth):
    """Crear dos filtros distintos → GET devuelve 2 items."""
    _crear_filtro(client, auth, name="Filtro A")
    _crear_filtro(client, auth, name="Filtro B")

    r = client.get("/api/v1/saved-filters", headers=auth)
    nombres = {i["name"] for i in r.json()["items"]}
    assert {"Filtro A", "Filtro B"} == nombres


# ---------------------------------------------------------------------------
# DELETE /saved-filters/{id}
# ---------------------------------------------------------------------------


def test_filtros_delete(client, auth):
    """POST → DELETE → 200 → GET → lista vacía."""
    _crear_filtro(client, auth, name="Para borrar")

    items = client.get("/api/v1/saved-filters", headers=auth).json()["items"]
    filter_id = items[0]["id"]

    r_del = client.delete(f"/api/v1/saved-filters/{filter_id}", headers=auth)
    assert r_del.status_code == 200
    assert r_del.json()["status"] == "ok"

    r_list = client.get("/api/v1/saved-filters", headers=auth)
    assert r_list.json()["items"] == []


def test_filtros_delete_ajeno(client, auth, api_db):
    """Filtro creado con key A → intento de borrado con key B → 404 (IDOR)."""
    from api.auth import create_api_key
    from db.users import create_user

    # Crear filtro con la key del fixture auth
    _crear_filtro(client, auth, name="Filtro ajeno")
    items = client.get("/api/v1/saved-filters", headers=auth).json()["items"]
    filter_id = items[0]["id"]

    # Segunda key para usuario distinto
    otro_user_id = create_user(email="otro-usuario@example.test", password_hash="test-hash")
    otra_key = create_api_key("otro-usuario", scopes="saved_filters:write", user_id=otro_user_id)
    otro_auth = {"X-API-Key": otra_key}

    r = client.delete(f"/api/v1/saved-filters/{filter_id}", headers=otro_auth)
    assert r.status_code == 404


def test_filtros_delete_no_existe(client, auth):
    """DELETE /99999 → 404."""
    r = client.delete("/api/v1/saved-filters/99999", headers=auth)
    assert r.status_code == 404
