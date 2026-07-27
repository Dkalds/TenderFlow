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
            "INSERT INTO api_keys(name, key_hash, created_at, is_active) "
            "VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
            ("test-read", "hash-abc", now_utc_iso(), 1),
        )

    # Leer con connect_read
    with connect_read() as conn:
        row = conn.execute("SELECT name FROM api_keys WHERE key_hash = ?", ("hash-abc",)).fetchone()
        assert row is not None
        assert row[0] == "test-read"


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


# ── _pg_connect_kwargs (timeouts + sslrootcert, hardening seguridad) ─────────


def test_pg_connect_kwargs_defaults(monkeypatch):
    from config import settings
    from db import connection as conn_mod

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000)
    monkeypatch.setattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 60_000)
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 10)
    monkeypatch.setattr(settings, "DATABASE_SSL_ROOT_CERT", "")

    kwargs = conn_mod._pg_connect_kwargs()
    assert kwargs["options"] == (
        "-c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000"
    )
    assert kwargs["connect_timeout"] == 10
    assert "sslrootcert" not in kwargs


def test_pg_connect_kwargs_zero_disables_timeouts(monkeypatch):
    """0 = sin límite: la opción correspondiente no debe incluirse."""
    from config import settings
    from db import connection as conn_mod

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 0)
    monkeypatch.setattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 0)
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 0)
    monkeypatch.setattr(settings, "DATABASE_SSL_ROOT_CERT", "")

    kwargs = conn_mod._pg_connect_kwargs()
    assert "options" not in kwargs
    assert "connect_timeout" not in kwargs


def test_pg_connect_kwargs_includes_sslrootcert_when_set(monkeypatch):
    from config import settings
    from db import connection as conn_mod

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000)
    monkeypatch.setattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 60_000)
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 10)
    monkeypatch.setattr(settings, "DATABASE_SSL_ROOT_CERT", "  db/certs/prod-ca-2021.crt  ")

    kwargs = conn_mod._pg_connect_kwargs()
    assert kwargs["sslrootcert"] == "db/certs/prod-ca-2021.crt"


# ── _get_pg_pool (pool Postgres: kwargs aplicados + redacción de DSN) ────────


def test_get_pg_pool_creates_pool_with_kwargs_and_logs(monkeypatch):
    """Camino feliz: el pool se crea con conn_kwargs y se loguea sin error."""
    from config import settings
    from db import connection as conn_mod

    monkeypatch.setattr(conn_mod, "_pg_pool", None)
    monkeypatch.setattr(conn_mod, "_database_url", lambda: "postgresql://u:p@h:5432/d")
    monkeypatch.setattr(settings, "DB_POOL_SIZE", 5)
    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000)
    monkeypatch.setattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 60_000)
    monkeypatch.setattr(settings, "DB_CONNECT_TIMEOUT", 10)
    monkeypatch.setattr(settings, "DATABASE_SSL_ROOT_CERT", "")

    created_kwargs: dict = {}

    class _FakePool:
        def __init__(self, **kwargs):
            created_kwargs.update(kwargs)

    import psycopg_pool

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", _FakePool)

    pool = conn_mod._get_pg_pool()
    assert isinstance(pool, _FakePool)
    assert created_kwargs["max_size"] == 5
    assert "statement_timeout=30000" in created_kwargs["kwargs"]["options"]

    monkeypatch.setattr(conn_mod, "_pg_pool", None)


def test_get_pg_pool_wraps_connection_error_without_leaking_dsn(monkeypatch):
    """Si ConnectionPool() falla, el error no debe filtrar la password del DSN."""
    from db import connection as conn_mod

    fake_dsn = "postgresql://u:s3cr3tpw@h:5432/d"  # pragma: allowlist secret
    monkeypatch.setattr(conn_mod, "_pg_pool", None)
    monkeypatch.setattr(conn_mod, "_database_url", lambda: fake_dsn)

    class _FakePool:
        def __init__(self, **kwargs):
            raise RuntimeError(f"connect failed: {fake_dsn}")

    import psycopg_pool

    monkeypatch.setattr(psycopg_pool, "ConnectionPool", _FakePool)

    import pytest

    with pytest.raises(RuntimeError) as exc_info:
        conn_mod._get_pg_pool()

    msg = str(exc_info.value)
    assert "s3cr3tpw" not in msg
    assert "No se pudo crear el pool Postgres" in msg


# ---------------------------------------------------------------------------
# Shim de paramstyle: escape de `%` literal (ADR-018)
# ---------------------------------------------------------------------------


def test_translate_qmarks_escapes_literal_percent_with_params(monkeypatch):
    """Un `%` dentro de un literal es dato, no placeholder.

    psycopg interpreta `%` como inicio de placeholder cuando la sentencia lleva
    parámetros, así que `LIKE 'daily|%'` reventaba con "only '%s', '%b', '%t'
    are allowed as placeholders". Era el caso de
    ExtractionRunRepository.load_recent_daily_statuses, que además captura la
    excepción y devuelve [] — la alerta de fallos consecutivos del feed diario
    nunca se disparaba en producción.
    """
    import db.connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)

    sql = "SELECT status FROM extraction_runs WHERE notas LIKE 'daily|%' LIMIT ?"
    out = conn_mod._translate_qmarks(sql, has_params=True)

    assert "'daily|%%'" in out
    assert out.endswith("LIMIT %s")


def test_translate_qmarks_leaves_percent_alone_without_params(monkeypatch):
    """Sin parámetros psycopg no interpreta `%`: doblarlo corrompería el dato."""
    import db.connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)

    sql = "SELECT * FROM t WHERE c LIKE 'x%'"
    assert conn_mod._translate_qmarks(sql, has_params=False) == sql


def test_translate_qmarks_does_not_touch_comments(monkeypatch):
    """El `%` de un comentario no llega al motor: no debe doblarse."""
    import db.connection as conn_mod

    monkeypatch.setattr(conn_mod, "is_postgres_backend", lambda: True)

    sql = "SELECT 1 -- 100% seguro\nWHERE a = ?"
    out = conn_mod._translate_qmarks(sql, has_params=True)

    assert "-- 100% seguro" in out
    assert "a = %s" in out
