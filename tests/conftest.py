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


def _infer_marker(path: str, name: str) -> str:
    """Infer the pytest marker for a test item based on path/name conventions."""
    p = path.lower().replace("\\", "/")
    n = name.lower()
    for token in _E2E_TOKENS:
        if token in p or token in n:
            return "e2e"
    for token in _LOAD_TOKENS:
        if token in p or token in n:
            return "load"
    for token in _PROPERTY_TOKENS:
        if token in p or token in n:
            return "property"
    # integration: explicit /integration/ path segment or test_integration_* name prefix
    if "/integration/" in p or "integration_" in n:
        return "integration"
    return "unit"


def pytest_collection_modifyitems(config, items):
    for item in items:
        marks_existing = {m.name for m in item.iter_markers()}
        if marks_existing & {"unit", "integration", "e2e", "property", "load"}:
            continue
        marker_name = _infer_marker(str(item.fspath), item.name)
        item.add_marker(getattr(pytest.mark, marker_name))


@pytest.fixture(autouse=True)
def _clear_service_data_caches():
    """Limpia las cachés de full-table de la capa de servicios entre tests.

    ``load_stats_dataframe`` / ``load_raw_adjudicaciones`` cachean el snapshot
    en memoria (TTL + señal de ingesta). En tests que mutan la BD y luego leen,
    una caché caliente serviría datos obsoletos; limpiarla antes/después aísla
    cada test.
    """
    from services.adjudicaciones import clear_raw_adj_cache
    from services.licitaciones import clear_stats_cache

    clear_stats_cache()
    clear_raw_adj_cache()
    yield
    clear_stats_cache()
    clear_raw_adj_cache()


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
