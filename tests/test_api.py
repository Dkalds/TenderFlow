"""Tests para la API REST FastAPI."""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    """DB temporal con migración 19 aplicada, cargada en el entorno de test."""
    import db.database as db_mod

    db_path = tmp_path / "test_api.db"
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "")

    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))

    db_mod.init_db()
    yield db_path
    db_mod.close_pool()
    db_mod.set_db_path_override(None)


@pytest.fixture()
def api_key(api_db):
    """Crea una API Key en la DB de test y devuelve el token en bruto."""
    from api.auth import create_api_key

    return create_api_key("test-key")


@pytest.fixture()
def client(api_db):
    """TestClient de FastAPI con DB temporal."""
    # Re-import para que tome la DB de test
    from api.app import app

    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests /api/v1/health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200

    def test_health_no_auth_required(self, client):
        """Health no debe pedir API Key."""
        resp = client.get("/api/v1/health")
        assert resp.status_code != 401

    def test_health_response_shape(self, client):
        data = client.get("/api/v1/health").json()
        assert "status" in data
        assert "db" in data
        assert "timestamp" in data

    def test_health_db_ok(self, client):
        data = client.get("/api/v1/health").json()
        assert data["db"] == "ok"


# ---------------------------------------------------------------------------
# Tests autenticación
# ---------------------------------------------------------------------------


class TestApiKeyAuth:
    def test_missing_key_returns_401(self, client):
        resp = client.get("/api/v1/licitaciones")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, client):
        resp = client.get("/api/v1/licitaciones", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_valid_key_returns_200(self, client, api_key):
        resp = client.get("/api/v1/licitaciones", headers={"X-API-Key": api_key})
        assert resp.status_code == 200

    def test_revoked_key_returns_401(self, client, api_key):
        from api.auth import hash_api_key, revoke_api_key

        key_hash = hash_api_key(api_key)
        revoke_api_key(key_hash)

        resp = client.get("/api/v1/licitaciones", headers={"X-API-Key": api_key})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests /api/v1/licitaciones
# ---------------------------------------------------------------------------


@pytest.fixture()
def seeded_client(api_db, api_key, monkeypatch):
    """Client con datos de prueba en la DB."""
    from db.database import connect

    with connect() as c:
        c.execute(
            "INSERT OR IGNORE INTO licitaciones "
            "(id_externo, titulo, descripcion, organo_contratacion, importe, estado, "
            " fecha_publicacion, ccaa, cpv, url, tecnologia, fecha_extraccion) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "LIC-001", "Sistema SAP ERP para AEAT",
                "Implantación SAP S/4HANA", "AEAT", 500000.0,
                "PUB", "2025-01-15", "Madrid", "72000000",
                "https://example.com/lic/001", "SAP", "2025-01-01",
            ],
        )
        c.execute(
            "INSERT OR IGNORE INTO licitaciones "
            "(id_externo, titulo, organo_contratacion, importe, estado, "
            " fecha_publicacion, ccaa, tecnologia, fecha_extraccion) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                "LIC-002", "Mantenimiento SAP Barcelona",
                "Diputació Barcelona", 120000.0,
                "EV", "2025-02-10", "Cataluña", "SAP", "2025-02-01",
            ],
        )
        c.commit()

    from api.app import app

    client = TestClient(app, raise_server_exceptions=True)
    client._api_key = api_key  # type: ignore[attr-defined]
    return client


class TestLicitacionesEndpoint:
    def _auth(self, client):
        return {"X-API-Key": client._api_key}

    def test_list_returns_items(self, seeded_client):
        resp = seeded_client.get(
            "/api/v1/licitaciones", headers=self._auth(seeded_client)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2

    def test_list_pagination_fields(self, seeded_client):
        data = seeded_client.get(
            "/api/v1/licitaciones?limit=1&offset=0", headers=self._auth(seeded_client)
        ).json()
        assert data["limit"] == 1
        assert data["offset"] == 0
        assert len(data["items"]) == 1

    def test_filter_by_ccaa(self, seeded_client):
        data = seeded_client.get(
            "/api/v1/licitaciones?ccaa=Cataluña", headers=self._auth(seeded_client)
        ).json()
        assert data["total"] == 1
        assert data["items"][0]["id_externo"] == "LIC-002"

    def test_filter_by_q(self, seeded_client):
        data = seeded_client.get(
            "/api/v1/licitaciones?q=AEAT", headers=self._auth(seeded_client)
        ).json()
        assert data["total"] >= 1

    def test_filter_by_estado(self, seeded_client):
        data = seeded_client.get(
            "/api/v1/licitaciones?estado=PUB", headers=self._auth(seeded_client)
        ).json()
        assert all(i["estado"] == "PUB" for i in data["items"])

    def test_get_detail_ok(self, seeded_client):
        resp = seeded_client.get(
            "/api/v1/licitaciones/LIC-001", headers=self._auth(seeded_client)
        )
        assert resp.status_code == 200
        assert resp.json()["id_externo"] == "LIC-001"

    def test_get_detail_not_found(self, seeded_client):
        resp = seeded_client.get(
            "/api/v1/licitaciones/NO-EXISTE", headers=self._auth(seeded_client)
        )
        assert resp.status_code == 404

    def test_limit_max_enforced(self, seeded_client):
        """Límite > 500 devuelve 422 Unprocessable Entity."""
        resp = seeded_client.get(
            "/api/v1/licitaciones?limit=9999", headers=self._auth(seeded_client)
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests paginación por cursor (T2)
# ---------------------------------------------------------------------------


class TestCursorPagination:
    def _auth(self, client):
        return {"X-API-Key": client._api_key}

    def test_first_page_no_cursor(self, seeded_client):
        resp = seeded_client.get(
            "/api/v1/licitaciones/cursor?limit=1",
            headers=self._auth(seeded_client),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "has_more" in data
        assert "next_cursor" in data
        assert data["limit"] == 1

    def test_cursor_round_trip(self, seeded_client):
        """Dos páginas con cursor cubren todos los ítems sin duplicados."""
        first = seeded_client.get(
            "/api/v1/licitaciones/cursor?limit=1",
            headers=self._auth(seeded_client),
        ).json()
        assert first["has_more"] is True
        assert first["next_cursor"] is not None
        first_id = first["items"][0]["id_externo"]

        second = seeded_client.get(
            f"/api/v1/licitaciones/cursor?limit=1&cursor={first['next_cursor']}",
            headers=self._auth(seeded_client),
        ).json()
        assert len(second["items"]) >= 1
        second_id = second["items"][0]["id_externo"]
        assert first_id != second_id

    def test_malformed_cursor_returns_400(self, seeded_client):
        """Cursor inválido devuelve 400."""
        resp = seeded_client.get(
            "/api/v1/licitaciones/cursor?cursor=!!!not-valid-base64!!!",
            headers=self._auth(seeded_client),
        )
        assert resp.status_code == 400

    def test_empty_result_no_next_cursor(self, seeded_client):
        """Un filtro que no devuelve resultados debe tener next_cursor=null."""
        resp = seeded_client.get(
            "/api/v1/licitaciones/cursor?tecnologia=NONEXISTENT",
            headers=self._auth(seeded_client),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["next_cursor"] is None
        assert data["has_more"] is False


# ---------------------------------------------------------------------------
# Tests expiración de API key (T3)
# ---------------------------------------------------------------------------


class TestApiKeyExpiration:
    def test_expired_key_returns_401(self, client, api_db):
        """Una API key con expires_at en el pasado devuelve 401."""
        from api.auth import create_api_key, hash_api_key
        from db.database import connect, now_utc_iso

        raw = create_api_key("expiring-key")
        key_hash = hash_api_key(raw)

        # Forzar expires_at al pasado
        past = "2020-01-01T00:00:00+00:00"
        with connect() as c:
            c.execute(
                "UPDATE api_keys SET expires_at = ? WHERE key_hash = ?",
                (past, key_hash),
            )

        resp = client.get("/api/v1/licitaciones", headers={"X-API-Key": raw})
        assert resp.status_code == 401

    def test_future_expiry_is_valid(self, client, api_db):
        """Una API key con expires_at en el futuro es válida."""
        from api.auth import create_api_key, hash_api_key
        from db.database import connect

        raw = create_api_key("future-key")
        key_hash = hash_api_key(raw)

        future = "2099-12-31T23:59:59+00:00"
        with connect() as c:
            c.execute(
                "UPDATE api_keys SET expires_at = ? WHERE key_hash = ?",
                (future, key_hash),
            )

        resp = client.get("/api/v1/licitaciones", headers={"X-API-Key": raw})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Tests /api/v1/adjudicaciones
# ---------------------------------------------------------------------------


class TestAdjudicacionesEndpoint:
    def _auth(self, api_key):
        return {"X-API-Key": api_key}

    def test_list_empty_ok(self, client, api_key):
        resp = client.get("/api/v1/adjudicaciones", headers=self._auth(api_key))
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data

    def test_list_no_auth(self, client):
        resp = client.get("/api/v1/adjudicaciones")
        assert resp.status_code == 401
