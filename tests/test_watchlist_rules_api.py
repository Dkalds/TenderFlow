"""Tests de la API /api/v1/watchlist/rules (CRUD + matches + preview).

Fixtures api_db, api_key, client heredados de conftest.py.
"""

from __future__ import annotations


def _auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def _seed_licitaciones() -> None:
    from db.database import connect

    rows = [
        ("L1", "Implantación SAP", "72000000", 100_000.0),
        ("L2", "Mantenimiento Oracle", "72500000", 5_000.0),
        ("L3", "Obras varias", "45000000", 2_000_000.0),
    ]
    with connect() as c:
        for lic_id, titulo, cpv, importe in rows:
            c.execute(
                "INSERT INTO licitaciones (id_externo, titulo, cpv, importe, fuente, "
                " fecha_publicacion, fecha_extraccion) "
                "VALUES (?, ?, ?, ?, 'placsp', '2026-01-01', datetime('now'))",
                (lic_id, titulo, cpv, importe),
            )


def test_requires_auth(client):
    assert client.get("/api/v1/watchlist/rules").status_code == 401


def test_crud_roundtrip(client, api_key):
    h = _auth(api_key)

    # crear
    r = client.post(
        "/api/v1/watchlist/rules",
        json={"nombre": "SAP", "keyword": "SAP", "frequency": "weekly"},
        headers=h,
    )
    assert r.status_code == 201
    rid = r.json()["id"]

    # listar (incluye match_count real)
    items = client.get("/api/v1/watchlist/rules", headers=h).json()["items"]
    assert len(items) == 1
    assert items[0]["keyword"] == "SAP"
    assert items[0]["frequency"] == "weekly"
    assert "match_count" in items[0]

    # actualizar
    assert (
        client.put(
            f"/api/v1/watchlist/rules/{rid}",
            json={"keyword": "Oracle"},
            headers=h,
        ).status_code
        == 200
    )
    items = client.get("/api/v1/watchlist/rules", headers=h).json()["items"]
    assert items[0]["keyword"] == "Oracle"

    # borrar
    assert client.delete(f"/api/v1/watchlist/rules/{rid}", headers=h).status_code == 200
    assert client.get("/api/v1/watchlist/rules", headers=h).json()["items"] == []


def test_update_inexistente_404(client, api_key):
    r = client.put("/api/v1/watchlist/rules/9999", json={"keyword": "x"}, headers=_auth(api_key))
    assert r.status_code == 404


def test_preview_cuenta_matches(client, api_key):
    _seed_licitaciones()
    r = client.post("/api/v1/watchlist/rules/preview", json={"cpv": "72"}, headers=_auth(api_key))
    assert r.status_code == 200
    assert r.json()["total"] == 2  # L1 + L2 (cpv 72*)


def test_matches_de_una_regla(client, api_key):
    _seed_licitaciones()
    h = _auth(api_key)
    rid = client.post("/api/v1/watchlist/rules", json={"keyword": "SAP"}, headers=h).json()["id"]

    data = client.get(f"/api/v1/watchlist/rules/{rid}/matches", headers=h).json()
    assert data["total"] == 1  # solo L1 (título SAP)
    assert [it["id_externo"] for it in data["items"]] == ["L1"]
