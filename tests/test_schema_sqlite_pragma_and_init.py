"""Smoke tests de ``safe_pragma``, ``init_db`` legacy y del servicio de auth.

Antes de ADR-020 este fichero cubría también la detección de backend
Turso/Hrana (retirado); lo que queda es el resto del contrato de
``safe_pragma`` con Postgres/SQLite y un par de regresiones de arranque.
"""

from __future__ import annotations

from unittest.mock import patch


def test_safe_pragma_skips_when_postgres_backend():
    """``safe_pragma`` no debe ejecutar nada con backend Postgres."""
    import db.connection as conn_mod

    executed: list[str] = []

    class FakeConn:
        def execute(self, stmt: str):
            executed.append(stmt)

    with patch.object(conn_mod, "is_postgres_backend", return_value=True):
        conn_mod.safe_pragma(FakeConn(), "PRAGMA query_only = ON")

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


def test_connect_read_emits_query_only_pragmas(tmp_db):
    """Regresión: ``connect_read()`` invoca ``safe_pragma`` con query_only ON/OFF.

    Tras la refactorización de db.database como fachada pura (P2-4),
    ``connect_read`` y ``safe_pragma`` residen en ``db.connection``.
    El patch debe apuntar al módulo canónico para capturar las invocaciones.
    """
    db_mod, _ = tmp_db
    import db.connection as conn_mod

    calls: list[str] = []

    def recorder(conn, stmt):
        calls.append(stmt)
        # No ejecutar nada — simula safe_pragma no-op

    with (
        patch.object(conn_mod, "safe_pragma", side_effect=recorder),
        db_mod.connect_read() as conn,
    ):
        row = conn.execute("SELECT 1").fetchone()
        assert row[0] == 1

    # connect_read debe invocar safe_pragma con query_only ON y OFF
    assert any("query_only" in c.lower() for c in calls)


def test_init_db_legacy_ml_feedback_without_tecnologia(tmp_path):
    """Regresión: ``init_db()`` no debe fallar si ``ml_feedback`` ya existe sin
    la columna ``tecnologia``.

    Reproduce el crash de arranque ``SQLite input error: no such column:
    tecnologia (at offset 69)`` en BDs legacy donde la migración Alembic v44
    no corrió por el path de ``init_db()``. El índice
    ``idx_ml_feedback_tecnologia`` debe crearse tras asegurar la columna.
    """
    import db.connection as conn_mod
    import db.database as db_mod

    db_path = tmp_path / "legacy.db"
    db_mod.close_pool()
    db_mod.set_db_path_override(str(db_path))
    try:
        # Semillar ml_feedback LEGACY (sin tecnologia/tecnologias_secundarias/model_version)
        with conn_mod.connect() as c:
            c.execute(
                "CREATE TABLE ml_feedback ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "expediente TEXT NOT NULL, "
                "relevante INTEGER NOT NULL, "
                "nota TEXT NOT NULL DEFAULT '', "
                "created_at TEXT NOT NULL)"
            )

        # init_db() no debe crashear pese a la tabla legacy preexistente.
        conn_mod._db_initialized = False
        db_mod.init_db()

        with conn_mod.connect_read() as c:
            cols = conn_mod.get_table_columns(c, "ml_feedback")
            idx_names = {
                r[0]
                for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='ml_feedback'"
                ).fetchall()
            }

        assert {"tecnologia", "tecnologias_secundarias", "model_version"} <= cols
        assert "idx_ml_feedback_tecnologia" in idx_names
    finally:
        db_mod.close_pool()
        db_mod.set_db_path_override(None)


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
