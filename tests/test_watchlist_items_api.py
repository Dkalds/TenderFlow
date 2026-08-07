"""Tests de la API /api/v1/watchlist/items (favoritos de licitaciones).

Fixtures api_db, client heredados de conftest.py. ``api_key`` se sobreescribe
localmente (ver más abajo).
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def api_key(api_db):
    """Override de conftest: vincula la key a un usuario real.

    Esta ruta resuelve organización server-side (``api/tenancy.py``), que
    necesita un ``users.id`` real para ``ensure_personal_organization``. La
    key sin vincular del fixture compartido usa su propio id como
    ``user_id`` postizo (compatibilidad dev/test de
    ``api/routes/dual_auth.py``), que no existe en ``users``.
    """
    from api.auth import create_api_key
    from db.users import create_user

    user_id = create_user(email="watchlist-items-api@example.test", password_hash="test-hash")
    return create_api_key("test-key", scopes="*", user_id=user_id)


def _auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _seed_licitaciones() -> None:
    from db.database import connect

    rows = [
        ("L1", "Implantación SAP", "72000000", 100_000.0, "ABIERTO", "2026-01-01"),
        ("L2", "Mantenimiento Oracle", "72500000", 5_000.0, "ABIERTO", "2026-01-02"),
    ]
    with connect() as c:
        for lic_id, titulo, cpv, importe, estado, fecha_pub in rows:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, cpv, importe, estado, "
                " fuente, fecha_publicacion, fecha_extraccion) "
                "VALUES (%s, %s, %s, %s, %s, 'placsp', %s, CURRENT_TIMESTAMP)",
                (lic_id, titulo, cpv, importe, estado, fecha_pub),
            )


def test_requires_auth(client):
    assert client.get("/api/v1/watchlist/items").status_code == 401


def test_add_list_remove_roundtrip(client, api_key):
    h = _auth(api_key)
    _seed_licitaciones()

    # crear
    r = client.post("/api/v1/watchlist/items", json={"id_externo": "L1"}, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert body["id_externo"] == "L1"

    # listar (enriquecido con datos de la licitación)
    items = client.get("/api/v1/watchlist/items", headers=h).json()["items"]
    assert len(items) == 1
    assert items[0]["id_externo"] == "L1"
    assert items[0]["titulo"] == "Implantación SAP"
    assert items[0]["importe"] == 100_000.0
    assert items[0]["estado"] == "ABIERTO"
    assert items[0]["fecha_publicacion"] == "2026-01-01"

    # borrar
    assert client.delete("/api/v1/watchlist/items/L1", headers=h).status_code == 204
    assert client.get("/api/v1/watchlist/items", headers=h).json()["items"] == []


def test_add_is_idempotent(client, api_key):
    h = _auth(api_key)
    _seed_licitaciones()

    r1 = client.post("/api/v1/watchlist/items", json={"id_externo": "L1"}, headers=h)
    r2 = client.post("/api/v1/watchlist/items", json={"id_externo": "L1"}, headers=h)
    assert r1.status_code == 201
    assert r2.status_code == 201

    items = client.get("/api/v1/watchlist/items", headers=h).json()["items"]
    assert len(items) == 1


def test_remove_inexistente_404(client, api_key):
    r = client.delete("/api/v1/watchlist/items/NOPE", headers=_auth(api_key))
    assert r.status_code == 404


def test_items_de_distintos_usuarios_no_se_mezclan(client, api_db):
    from api.auth import create_api_key
    from db.users import create_user

    _seed_licitaciones()
    user_a = create_user(email="items-user-a@example.test", password_hash="test-hash")
    user_b = create_user(email="items-user-b@example.test", password_hash="test-hash")
    key_a = create_api_key("user-a", scopes="watchlist:read,watchlist:write", user_id=user_a)
    key_b = create_api_key("user-b", scopes="watchlist:read,watchlist:write", user_id=user_b)

    client.post("/api/v1/watchlist/items", json={"id_externo": "L1"}, headers=_auth(key_a))
    client.post("/api/v1/watchlist/items", json={"id_externo": "L2"}, headers=_auth(key_b))

    items_a = client.get("/api/v1/watchlist/items", headers=_auth(key_a)).json()["items"]
    items_b = client.get("/api/v1/watchlist/items", headers=_auth(key_b)).json()["items"]

    assert [it["id_externo"] for it in items_a] == ["L1"]
    assert [it["id_externo"] for it in items_b] == ["L2"]
