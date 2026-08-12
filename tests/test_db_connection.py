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
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            ("test-read", "hash-abc", now_utc_iso(), 1),
        )

    # Leer con connect_read
    with connect_read() as conn:
        row = conn.execute(
            "SELECT name FROM api_keys WHERE key_hash = %s", ("hash-abc",)
        ).fetchone()
        assert row is not None
        assert row[0] == "test-read"


# ── close_pool thread-safety ─────────────────────────────────────────────────


def test_unit_close_pool_closes_pg_pool(tmp_db):
    """close_pool() cierra el pool Postgres compartido y permite reabrirlo.

    Antes verificaba que se limpiaba una conexión thread-local: ese camino era
    del backend SQLite y desapareció con ADR-021.
    """
    db_mod, _ = tmp_db

    from db import connection as conn_mod

    with db_mod.connect() as c:
        c.execute("SELECT 1")
    assert conn_mod._pg_pool is not None

    db_mod.close_pool()
    assert conn_mod._pg_pool is None

    # El pool se recrea de forma transparente en el siguiente uso.
    with db_mod.connect() as c:
        assert c.execute("SELECT 1").fetchone()[0] == 1


# ── Convención de paramstyle (el shim qmark se retiró en 2026-08) ────────────
#
# Los tests de `_translate_qmarks` desaparecen con la función: el SQL del
# proyecto se escribe ya en el paramstyle de psycopg3 y no hay traducción en
# runtime que verificar. Lo que sigue habiendo que garantizar es la propiedad
# que aquel shim aseguraba de rebote y que causó un bug de producción
# (ADR-018): un `%` literal dentro de una sentencia CON parámetros tiene que ir
# doblado, o psycopg lo lee como inicio de placeholder.


def test_like_con_porcentaje_literal_y_parametros(tmp_db):
    """`LIKE 'daily|%%'` + `LIMIT %s` en la misma sentencia, contra Postgres real.

    Es el caso exacto que rompía en producción: la query capturaba la excepción
    y devolvía `[]`, así que la alerta de fallos consecutivos del feed diario
    nunca se disparaba, y la suite no lo veía porque corría sobre SQLite.
    """
    from db.database import connect, now_utc_iso

    with connect() as c:
        for i, notas in enumerate(("daily|ok", "otro|ok")):
            c.execute(
                "INSERT INTO extraction_runs (run_id, started_at, status, notas) "
                "VALUES (%s, %s, %s, %s)",
                (f"run-{i}", now_utc_iso(), "ok", notas),
            )
        filas = c.execute(
            "SELECT notas FROM extraction_runs WHERE notas LIKE 'daily|%%' LIMIT %s",
            (10,),
        ).fetchall()

    assert [f[0] for f in filas] == ["daily|ok"]


def test_porcentaje_literal_sin_parametros_no_se_dobla(tmp_db):
    """Sin parámetros, psycopg no interpreta `%`: el literal va tal cual."""
    from db.database import connect, now_utc_iso

    with connect() as c:
        c.execute(
            "INSERT INTO extraction_runs (run_id, started_at, status, notas) "
            "VALUES (%s, %s, %s, %s)",
            ("run-seed", now_utc_iso(), "ok", "seed|x"),
        )
        filas = c.execute("SELECT notas FROM extraction_runs WHERE notas LIKE 'seed|%'").fetchall()

    assert [f[0] for f in filas] == ["seed|x"]


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


# ── configure: los timeouts se fijan con SET, no solo por `options` ──────────


class _FakeCursor:
    def __init__(self, ejecutadas):
        self._ejecutadas = ejecutadas

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._ejecutadas.append((sql, params))


class _FakeConn:
    def __init__(self, *, autocommit=False):
        self.autocommit = autocommit
        self.ejecutadas: list[tuple] = []
        self.commits = 0

    def cursor(self):
        return _FakeCursor(self.ejecutadas)

    def commit(self):
        self.commits += 1


def _ajustes(conn):
    """{nombre: valor} de los set_config que recibió la conexión."""
    return {params[0]: params[1] for _, params in conn.ejecutadas if params}


def test_configure_aplica_los_timeouts_por_sesion(monkeypatch):
    """El pool fija statement_timeout con SET además de pedirlo por `options`.

    `options` es un parámetro de arranque de libpq y no está llegando a las
    conexiones de la API a través del pooler: se veían consultas de 110 s con
    el timeout puesto a 30 s. Un `set_config` viaja como sentencia normal.
    """
    from config import settings
    from db import connection as conn_mod

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000)
    monkeypatch.setattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 60_000)

    conn = _FakeConn()
    conn_mod._make_pg_configure(read_only=False)(conn)

    ajustes = _ajustes(conn)
    assert ajustes["statement_timeout"] == "30000"
    assert ajustes["idle_in_transaction_session_timeout"] == "60000"
    assert "default_transaction_read_only" not in ajustes
    # Sin autocommit el `set_config` abrió transacción: sin commit, el reset
    # del pool haría rollback y los ajustes se perderían.
    assert conn.commits == 1


def test_configure_del_pool_de_lectura_fija_el_modo_solo_lectura(monkeypatch):
    """El read-only del pool de lectura es una garantía, no una optimización."""
    from config import settings
    from db import connection as conn_mod

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000)
    monkeypatch.setattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 60_000)

    conn = _FakeConn(autocommit=True)
    conn_mod._make_pg_configure(read_only=True)(conn)

    assert _ajustes(conn)["default_transaction_read_only"] == "on"
    assert conn.commits == 0, "en autocommit no hay transacción que confirmar"


def test_configure_con_timeouts_desactivados_no_ejecuta_nada(monkeypatch):
    """A 0 (sin límite) no se emite ningún SET."""
    from config import settings
    from db import connection as conn_mod

    monkeypatch.setattr(settings, "DB_STATEMENT_TIMEOUT_MS", 0)
    monkeypatch.setattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 0)

    conn = _FakeConn()
    conn_mod._make_pg_configure(read_only=False)(conn)

    assert conn.ejecutadas == []
    assert conn.commits == 0


def test_perfil_batch_recibe_un_techo_mas_alto():
    """Un job de Actions no comparte el pool de 12 de la API y sí tiene
    consultas legítimas de más de 30 s (la auditoría diaria mide 76 s)."""
    from config.settings import Settings

    api = Settings(APP_PROFILE="api", ENV="dev")
    batch = Settings(APP_PROFILE="scraper", ENV="dev")
    explicito = Settings(APP_PROFILE="scraper", ENV="dev", DB_STATEMENT_TIMEOUT_MS=15_000)

    assert api.DB_STATEMENT_TIMEOUT_MS == 30_000
    assert batch.DB_STATEMENT_TIMEOUT_MS > api.DB_STATEMENT_TIMEOUT_MS
    assert explicito.DB_STATEMENT_TIMEOUT_MS == 15_000, "un valor del entorno gana siempre"


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
