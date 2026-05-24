"""Tests para db/connection.py — helpers de fecha, safe_pragma y connect."""

from __future__ import annotations

from datetime import UTC, datetime

# ── now_utc / now_utc_iso ────────────────────────────────────────────────────


def test_now_utc_returns_utc_datetime():
    from db.connection import now_utc

    result = now_utc()
    assert isinstance(result, datetime)
    # Debe ser timezone-aware (UTC)
    assert result.tzinfo is not None
    assert result.tzinfo == UTC


def test_now_utc_iso_returns_iso_string():
    from db.connection import now_utc_iso

    result = now_utc_iso()
    assert isinstance(result, str)
    # Debe ser parseable como datetime ISO
    parsed = datetime.fromisoformat(result)
    assert parsed.tzinfo is not None


def test_now_utc_iso_is_recent():
    from db.connection import now_utc_iso

    before = datetime.now(UTC)
    result = now_utc_iso()
    after = datetime.now(UTC)

    parsed = datetime.fromisoformat(result)
    assert before <= parsed <= after


# ── safe_pragma ───────────────────────────────────────────────────────────────


def test_safe_pragma_does_not_raise_on_valid_stmt(tmp_db):
    """safe_pragma ejecuta sin error un PRAGMA válido."""
    db_mod, _ = tmp_db
    from db.connection import safe_pragma

    with db_mod.connect() as conn:
        # No debe lanzar ninguna excepción
        safe_pragma(conn, "PRAGMA journal_mode")


def test_safe_pragma_silences_invalid_stmt(tmp_db):
    """safe_pragma absorbe errores de PRAGMAs inválidos."""
    db_mod, _ = tmp_db
    from db.connection import safe_pragma

    with db_mod.connect() as conn:
        # Un PRAGMA inexistente no debe propagar excepción
        safe_pragma(conn, "PRAGMA this_does_not_exist_xyz = 42")


# ── connect / connect_read ────────────────────────────────────────────────────


def test_connect_returns_working_connection(tmp_db):
    """connect() devuelve una conexión con la que se puede hacer SELECT."""
    db_mod, _ = tmp_db

    with db_mod.connect() as conn:
        result = conn.execute("SELECT 1").fetchone()
        assert result is not None
        assert result[0] == 1


def test_connect_read_returns_working_connection(tmp_db):
    """connect_read() devuelve una conexión que puede leer."""
    _db_mod, _ = tmp_db
    from db.connection import connect_read

    with connect_read() as conn:
        result = conn.execute("SELECT 1").fetchone()
        assert result is not None
        assert result[0] == 1


def test_connect_read_after_write(tmp_db):
    """connect_read() ve los datos escritos con connect()."""
    db_mod, _ = tmp_db
    from db.connection import connect_read, now_utc_iso

    # Escribir algo — incluye created_at (NOT NULL) para evitar INSERT silencioso
    with db_mod.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO api_keys(name, key_hash, created_at, is_active) "
            "VALUES (?, ?, ?, ?)",
            ("test-read", "hash-abc", now_utc_iso(), 1),
        )

    # Leer con connect_read
    with connect_read() as conn:
        row = conn.execute("SELECT name FROM api_keys WHERE key_hash = ?", ("hash-abc",)).fetchone()
        assert row is not None
        assert row[0] == "test-read"


# ── is_turso_backend ─────────────────────────────────────────────────────────


def test_is_turso_backend_false_without_url(tmp_db):
    """Con _DB_PATH_OVERRIDE activo (tmp_db), is_turso_backend devuelve False."""
    from db.connection import is_turso_backend

    # tmp_db setea _DB_PATH_OVERRIDE → not _DB_PATH_OVERRIDE es False → retorna False
    assert is_turso_backend() is False
