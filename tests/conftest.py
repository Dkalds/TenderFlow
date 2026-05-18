"""Fixtures compartidos para aislar la BD en tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def tmp_db(monkeypatch, tmp_path):
    """BD SQLite temporal con migraciones aplicadas. Aislada por test."""
    import db.database as db_mod

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("TURSO_DATABASE_URL", "")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "")

    # Usar DI hook en vez de importlib.reload() masivo
    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))

    db_mod.init_db()
    yield db_mod, tmp_path
    db_mod.close_pool()
    db_mod.set_db_path_override(None)


# ── Fixtures compartidos para tests de la API REST ───────────────────────


@pytest.fixture()
def api_db(tmp_path, monkeypatch):
    """BD temporal con todas las migraciones, para tests de API."""
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
    """TestClient de FastAPI con DB temporal (raise_server_exceptions=True)."""
    from api.app import app

    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def auth(api_key):
    """Headers de autenticación con la API key de test."""
    return {"X-API-Key": api_key}
