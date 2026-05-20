"""Fixtures compartidos para aislar la BD en tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# ── Auto-marking de tests por convención de nombre ──────────────────────────
# Evita tener que anotar manualmente los ~70 tests existentes. Reglas:
#   - test_*property* / test_parser_properties → property
#   - test_*performance* / test_*load*         → load
#   - test_*e2e* / test_visual_regression / test_dashboard_smoke → e2e
#   - test_integration_*, test_*_integration   → integration
#   - todo lo demás                            → unit (default)
_E2E_TOKENS = ("_e2e", "visual_regression", "dashboard_smoke", "dashboard_pages")
_LOAD_TOKENS = ("performance", "load")
_PROPERTY_TOKENS = ("property", "properties", "property_based")
_INTEGRATION_TOKENS = ("integration_e2e",)  # explícito; resto queda como unit


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = str(item.fspath).lower()
        name = item.name.lower()
        marks_existing = {m.name for m in item.iter_markers()}

        applied = False
        for token in _E2E_TOKENS:
            if token in path or token in name:
                if "e2e" not in marks_existing:
                    item.add_marker(pytest.mark.e2e)
                applied = True
                break
        if applied:
            continue
        for token in _LOAD_TOKENS:
            if token in path or token in name:
                if "load" not in marks_existing:
                    item.add_marker(pytest.mark.load)
                applied = True
                break
        if applied:
            continue
        for token in _PROPERTY_TOKENS:
            if token in path or token in name:
                if "property" not in marks_existing:
                    item.add_marker(pytest.mark.property)
                applied = True
                break
        if applied:
            continue
        for token in _INTEGRATION_TOKENS:
            if token in path or token in name:
                if "integration" not in marks_existing:
                    item.add_marker(pytest.mark.integration)
                applied = True
                break
        if applied:
            continue
        # default
        if not (marks_existing & {"unit", "integration", "e2e", "property", "load"}):
            item.add_marker(pytest.mark.unit)


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
