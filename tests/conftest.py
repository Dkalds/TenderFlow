"""Fixtures compartidos para aislar la BD en tests."""

from __future__ import annotations

import pytest


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
