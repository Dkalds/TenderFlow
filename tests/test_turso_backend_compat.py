"""Smoke tests para detectar incompatibilidades del backend Turso/Hrana.

No requieren credenciales reales: validan la lógica de detección y los
helpers que evitan emitir sentencias no soportadas (PRAGMA) cuando la
configuración apunta a Turso. Estos tests reproducen la regresión que
provocó el fallo runtime de ``PRAGMA query_only`` en producción.
"""

from __future__ import annotations

from unittest.mock import patch


def test_is_turso_backend_false_when_path_override(tmp_db):
    """Con override de tests, nunca se considera backend Turso."""
    db_mod, _ = tmp_db
    assert db_mod.is_turso_backend() is False


def test_is_turso_backend_true_when_credentials_set(monkeypatch):
    """Con TURSO_DATABASE_URL + token y sin override, devuelve True."""
    import db.database as db_mod

    db_mod.close_pool()
    db_mod.set_db_path_override(None)

    with (
        patch.object(db_mod.settings, "TURSO_DATABASE_URL", "libsql://fake.turso.io"),
        patch.object(db_mod.settings, "TURSO_AUTH_TOKEN", "fake-token"),
    ):
        assert db_mod.is_turso_backend() is True


def test_is_turso_backend_false_when_token_missing(monkeypatch):
    """Sin token, no se considera Turso aunque haya URL."""
    import db.database as db_mod

    db_mod.close_pool()
    db_mod.set_db_path_override(None)

    with (
        patch.object(db_mod.settings, "TURSO_DATABASE_URL", "libsql://fake.turso.io"),
        patch.object(db_mod.settings, "TURSO_AUTH_TOKEN", ""),
    ):
        assert db_mod.is_turso_backend() is False


def test_safe_pragma_skips_when_turso_backend():
    """``safe_pragma`` no debe ejecutar nada si is_turso_backend() es True."""
    import db.database as db_mod

    executed: list[str] = []

    class FakeConn:
        def execute(self, stmt: str):
            executed.append(stmt)

    with patch.object(db_mod, "is_turso_backend", return_value=True):
        db_mod.safe_pragma(FakeConn(), "PRAGMA query_only = ON")

    assert executed == []


def test_safe_pragma_executes_on_local_sqlite(tmp_db):
    """En SQLite local, ``safe_pragma`` debe ejecutar la sentencia."""
    db_mod, _ = tmp_db
    executed: list[str] = []

    class FakeConn:
        def execute(self, stmt: str):
            executed.append(stmt)

    db_mod.safe_pragma(FakeConn(), "PRAGMA query_only = ON")
    assert executed == ["PRAGMA query_only = ON"]


def test_safe_pragma_silences_exceptions(tmp_db):
    """Errores en PRAGMA no deben propagarse (son optimizaciones)."""
    db_mod, _ = tmp_db

    class BoomConn:
        def execute(self, stmt: str):
            raise RuntimeError("pragma not supported")

    # No debería lanzar
    db_mod.safe_pragma(BoomConn(), "PRAGMA foo")


def test_connect_read_does_not_emit_pragmas_on_turso(tmp_db):
    """Regresión: ``connect_read()`` no debe emitir PRAGMA en Turso/Hrana.

    Patcheamos ``safe_pragma`` para grabar invocaciones y simulamos backend
    Turso. El context manager debe abrir/cerrar sin emitir PRAGMA alguno.
    """
    db_mod, _ = tmp_db

    calls: list[str] = []

    def recorder(conn, stmt):
        calls.append(stmt)
        # No ejecutar nada (simula Hrana: safe_pragma no-op)

    with (
        patch.object(db_mod, "is_turso_backend", return_value=True),
        patch.object(db_mod, "safe_pragma", side_effect=recorder),
        db_mod.connect_read() as conn,
    ):
        row = conn.execute("SELECT 1").fetchone()
        assert row[0] == 1

    # safe_pragma se invocó (con query_only ON/OFF) pero gracias al patch
    # nada se ejecutó realmente sobre la conexión Hrana-like.
    assert any("query_only" in c.lower() for c in calls)


def test_lookup_active_key_returns_none_when_missing(tmp_db):
    """Smoke test del servicio de auth: key inexistente devuelve None."""
    from services import auth as auth_service

    assert auth_service.lookup_active_key("nonexistent-hash") is None


def test_get_active_scopes_returns_none_when_missing(tmp_db):
    """Smoke test del helper síncrono del middleware /metrics."""
    from services import auth as auth_service

    assert auth_service.get_active_scopes("nonexistent-hash") is None


def test_insert_and_lookup_api_key_roundtrip(tmp_db):
    """End-to-end mínimo del servicio de auth (sin pasar por FastAPI)."""
    from services import auth as auth_service

    auth_service.insert_api_key(
        key_hash="smoke-hash-1",
        name="smoke-test",
        scopes="metrics:read",
        prefix="smoke123",
        user_id=None,
        expires_at=None,
    )
    record = auth_service.lookup_active_key("smoke-hash-1")
    assert record is not None
    assert record.scopes == "metrics:read"
    assert auth_service.get_active_scopes("smoke-hash-1") == "metrics:read"

    assert auth_service.deactivate_key("smoke-hash-1") is True
    assert auth_service.lookup_active_key("smoke-hash-1") is None
