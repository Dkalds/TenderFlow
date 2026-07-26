"""Tests de la API /api/v1/watchlist/items (favoritos de licitaciones).

Fixtures api_db, api_key, client heredados de conftest.py.
"""

from __future__ import annotations


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
                "VALUES (?, ?, ?, ?, ?, 'placsp', ?, datetime('now'))",
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

    _seed_licitaciones()
    key_a = create_api_key("user-a", scopes="watchlist:read,watchlist:write")
    key_b = create_api_key("user-b", scopes="watchlist:read,watchlist:write")

    client.post("/api/v1/watchlist/items", json={"id_externo": "L1"}, headers=_auth(key_a))
    client.post("/api/v1/watchlist/items", json={"id_externo": "L2"}, headers=_auth(key_b))

    items_a = client.get("/api/v1/watchlist/items", headers=_auth(key_a)).json()["items"]
    items_b = client.get("/api/v1/watchlist/items", headers=_auth(key_b)).json()["items"]

    assert [it["id_externo"] for it in items_a] == ["L1"]
    assert [it["id_externo"] for it in items_b] == ["L2"]
