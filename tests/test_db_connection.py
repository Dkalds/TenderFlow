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


# ── close_pool thread-safety ─────────────────────────────────────────────────


def test_unit_close_pool_clears_thread_local(tmp_db):
    """close_pool() cierra la conexión thread-local y la limpia."""
    db_mod, _ = tmp_db

    from db import connection as conn_mod

    # Ensure a thread-local connection exists
    with db_mod.connect() as c:
        c.execute("SELECT 1")

    # Now close_pool should clear it
    db_mod.close_pool()
    assert getattr(conn_mod._local, "conn", None) is None


def test_unit_close_pool_nullifies_pool_under_lock(tmp_db):
    """close_pool() sets _pool to None atomically under _pool_lock."""
    import queue as _queue_mod

    from db import connection as conn_mod

    # Simulate a pool existing (even in SQLite-local mode for test purposes)
    fake_pool: _queue_mod.Queue[object] = _queue_mod.Queue(maxsize=4)
    original_pool = conn_mod._pool
    original_active = conn_mod._pool_active
    try:
        conn_mod._pool = fake_pool  # type: ignore[assignment]
        conn_mod._pool_active = 0

        conn_mod.close_pool()

        assert conn_mod._pool is None
        assert conn_mod._pool_active == 0
    finally:
        conn_mod._pool = original_pool
        conn_mod._pool_active = original_active


def test_unit_close_pool_drains_queued_connections(tmp_db):
    """close_pool() drains and closes all connections in the pool."""
    import queue as _queue_mod
    from unittest.mock import MagicMock

    from db import connection as conn_mod

    fake_pool: _queue_mod.Queue[object] = _queue_mod.Queue(maxsize=4)
    mock_conn1 = MagicMock()
    mock_conn2 = MagicMock()
    fake_pool.put(mock_conn1)
    fake_pool.put(mock_conn2)

    original_pool = conn_mod._pool
    original_active = conn_mod._pool_active
    try:
        conn_mod._pool = fake_pool  # type: ignore[assignment]
        conn_mod._pool_active = 2

        conn_mod.close_pool()

        mock_conn1.close.assert_called_once()
        mock_conn2.close.assert_called_once()
        assert conn_mod._pool is None
        assert conn_mod._pool_active == 0
    finally:
        conn_mod._pool = original_pool
        conn_mod._pool_active = original_active


def test_unit_return_conn_closes_orphan_when_pool_none(tmp_db):
    """_return_conn closes the connection if _pool was already nullified."""
    from unittest.mock import MagicMock, patch

    from db import connection as conn_mod

    mock_conn = MagicMock()

    original_pool = conn_mod._pool
    try:
        conn_mod._pool = None

        # Patch is_turso_backend to return True so _return_conn enters pool path
        with patch.object(conn_mod, "is_turso_backend", return_value=True):
            with patch.object(conn_mod.settings, "DB_POOL_SIZE", 4):
                conn_mod._return_conn(mock_conn)

        mock_conn.close.assert_called_once()
    finally:
        conn_mod._pool = original_pool


# ── _translate_qmarks (shim qmark -> %s, ADR-016) ────────────────────────────
#
# Riesgo identificado en la auditoria de migracion F3b (2026-07-05): ADR-016
# declaraba "unit tests exhaustivos del shim" como mitigacion, pero no existia
# ninguno. Un bug real de este shim (regex de string literal con semantica de
# escape \\ estilo C/Python en vez de SQL estandar) corrompio en silencio el
# conteo de placeholders en queries con ESCAPE '\' seguido de mas '?' (patron
# usado en los fallbacks LIKE de db/repositories/licitaciones.py), detectado
# recien al ejecutar contra Postgres real.


def test_translate_qmarks_noop_when_not_postgres(monkeypatch):
    from db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: False)
    sql = "SELECT * FROM t WHERE a = ? AND b = ?"
    assert conn_mod._translate_qmarks(sql) == sql


def test_translate_qmarks_basic_replacement(monkeypatch):
    from db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)
    sql = "SELECT * FROM t WHERE a = ? AND b = ?"
    assert conn_mod._translate_qmarks(sql) == "SELECT * FROM t WHERE a = %s AND b = %s"


def test_translate_qmarks_ignores_placeholder_inside_single_quoted_string(monkeypatch):
    from db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)
    sql = "SELECT * FROM t WHERE a = ? AND b = 'literal ? not a placeholder'"
    result = conn_mod._translate_qmarks(sql)
    assert result == "SELECT * FROM t WHERE a = %s AND b = 'literal ? not a placeholder'"


def test_translate_qmarks_handles_doubled_quote_escape(monkeypatch):
    """SQL estándar escapa una comilla dentro de un string doblándola (''), no con \\'."""
    from db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)
    sql = "SELECT * FROM t WHERE name = 'it''s a ? test' AND id = ?"
    result = conn_mod._translate_qmarks(sql)
    assert result == "SELECT * FROM t WHERE name = 'it''s a ? test' AND id = %s"


def test_translate_qmarks_escape_backslash_clause_does_not_swallow_later_placeholders(
    monkeypatch,
):
    """Regresión: ESCAPE '\\' no es un string sin cerrar en SQL estándar.

    Bug real encontrado en F3b: el regex previo trataba \\' dentro de comillas
    simples como una comilla escapada (semántica C/Python), tragándose el resto
    de la query -- incluidos placeholders reales -- hasta la siguiente comilla.
    Esto rompía silenciosamente like_fallback_search/fetch_for_pdf/
    search_like_for_ask (todos usan ``LIKE ? ESCAPE '\\'``).
    """
    from db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)
    sql = (
        "SELECT id_externo FROM licitaciones "
        "WHERE titulo ILIKE ? ESCAPE '\\' OR descripcion ILIKE ? ESCAPE '\\' "
        "LIMIT ?"
    )
    result = conn_mod._translate_qmarks(sql)
    assert result.count("%s") == 3
    assert "?" not in result


def test_translate_qmarks_ignores_line_comment(monkeypatch):
    from db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)
    sql = "SELECT * FROM t WHERE a = ? -- this is a ? in a comment\n"
    result = conn_mod._translate_qmarks(sql)
    # El placeholder real se traduce; el "?" dentro del comentario queda intacto.
    assert result == "SELECT * FROM t WHERE a = %s -- this is a ? in a comment\n"


def test_translate_qmarks_ignores_block_comment(monkeypatch):
    from db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)
    sql = "SELECT * FROM t /* a ? in a block comment */ WHERE a = ?"
    result = conn_mod._translate_qmarks(sql)
    assert result.count("%s") == 1
    assert "/* a ? in a block comment */" in result
