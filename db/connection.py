"""Gestión del pool de conexiones SQLite / Turso (libSQL) y Postgres (psycopg3).

Este módulo centraliza toda la lógica de conexión: creación, pooling thread-safe,
context managers ``connect()`` / ``connect_read()``, y helpers de diagnóstico.
No contiene lógica de dominio ni DDL; esos residen en ``db.schema`` y ``db.upsert``.

Backends soportados (ADR-016):
- **SQLite local** (default dev): sin configuración adicional.
- **Turso/libSQL** (producción legacy): via ``TURSO_DATABASE_URL`` + ``TURSO_AUTH_TOKEN``.
- **Postgres / Supabase** (destino F3): via ``DATABASE_URL`` (postgresql://...).
  Precedencia: DATABASE_URL > TURSO_* > SQLite local.

Shim de paramstyle (F3a → F5):
  El código existente usa ``?`` (qmark). psycopg3 usa ``%s``. El shim
  ``_translate_qmarks(sql)`` reescribe ``?``→``%s`` respetando literales y
  comentarios. Se activa automáticamente cuando el backend es Postgres.
  F5 (refactor de repositories) convertirá los sitios a ``%s`` nativo.
"""

from __future__ import annotations

import os
import queue as _queue_mod
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from pydantic import SecretStr

from config import settings
from observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Utilidades de tiempo
# ---------------------------------------------------------------------------


def now_utc() -> datetime:
    """Devuelve datetime actual en UTC (aware). Reemplaza datetime.utcnow()."""
    return datetime.now(UTC)


def now_utc_iso() -> str:
    """ISO 8601 del instante actual en UTC."""
    return now_utc().isoformat()


# ---------------------------------------------------------------------------
# Detección de backend (ADR-016)
# ---------------------------------------------------------------------------


def _database_url() -> str:
    """Devuelve DATABASE_URL del entorno o cadena vacía.

    ``settings.DATABASE_URL`` es un ``SecretStr`` en el caso normal, pero los
    tests hacen ``monkeypatch.setattr(settings, "DATABASE_URL", "")`` con un
    ``str`` plano — se soportan ambas formas.
    """
    env_val = os.environ.get("DATABASE_URL", "")
    if env_val:
        return env_val
    attr_val = getattr(settings, "DATABASE_URL", "")
    if isinstance(attr_val, SecretStr):
        return attr_val.get_secret_value()
    return attr_val or ""


def is_postgres_backend() -> bool:
    """True si DATABASE_URL está configurada y apunta a Postgres/Supabase.

    Excepción: si hay un ``_DB_PATH_OVERRIDE`` activo (tests con tmp_db),
    siempre devuelve False para que los tests usen SQLite local.
    """
    # Acceder via globals() para evitar forward-reference (definida más abajo)
    if globals().get("_DB_PATH_OVERRIDE") is not None:
        return False  # tests siempre usan SQLite
    url = _database_url()
    return bool(url and url.startswith(("postgresql://", "postgres://")))


# ---------------------------------------------------------------------------
# Shim qmark → %s (activo solo con Postgres, F3a → F5)
# ---------------------------------------------------------------------------

# Patrón para tokenizar SQL y detectar ? fuera de literales/comentarios.
# Captura: strings simples, strings dobles, comentarios de línea, bloque, y ?
#
# IMPORTANTE: los literales SQL estándar (Postgres con standard_conforming_strings=on,
# el default) NO usan backslash como escape -- una comilla literal dentro de un string
# se escribe doblada (''), no con \'. Un patrón tipo (?:[^'\\]|\\.)* trata \' como
# "comilla escapada" y NO cierra el string ahi, tragándose el resto de la query
# (incluyendo placeholders ? reales) como si siguiera dentro del literal. Esto rompe
# de forma silenciosa cualquier SQL con ESCAPE '\' seguido de más '?' (patrón usado en
# los fallbacks LIKE de db/repositories/licitaciones.py). Por eso aquí NO se trata
# el backslash como escape: solo '' (comilla doblada) cierra/reabre un string.
_SQL_TOKEN_RE = re.compile(
    r"('(?:[^']|'')*')"  # string comillas simples (SQL estándar: '' escapa, no \')
    r'|("(?:[^"]|"")*")'  # identificador comillas dobles (mismo criterio)
    r"|(--[^\n]*)"  # comentario de línea
    r"|(/\*.*?\*/)"  # comentario de bloque (non-greedy)
    r"|(\?)",  # placeholder qmark
    re.DOTALL,
)


def _translate_qmarks(sql: str) -> str:
    """Reescribe ``?`` → ``%s`` en SQL respetando literales y comentarios.

    Solo activo cuando el backend es Postgres. No-op en SQLite/Turso.
    """
    if not is_postgres_backend():
        return sql

    def _replace(m: re.Match[str]) -> str:
        # Grupos 1-4: strings/comentarios — preservar tal cual
        if m.group(5) is None:
            return m.group(0)
        return "%s"

    return _SQL_TOKEN_RE.sub(_replace, sql)


# ---------------------------------------------------------------------------
# Adaptador psycopg3 que aplica el shim automáticamente
# ---------------------------------------------------------------------------


class _PgConnAdapter:
    """Envuelve una conexión psycopg3 y traduce qmark→%s en execute/executemany.

    Expone la misma interfaz mínima que las conexiones libsql para que los
    call-sites existentes funcionen sin cambios:
      - execute(sql, params) → cursor con fetchone/fetchall/description
      - executemany(sql, seq)
      - commit() / rollback()
      - close()

    El shim se aplica en execute/executemany. description es un alias de
    cursor.description de la última query.
    """

    def __init__(self, pg_conn: Any) -> None:
        self._conn = pg_conn
        self._cur: Any = None

    def execute(self, sql: str, params: Any = None) -> _PgConnAdapter:
        translated = _translate_qmarks(sql)
        self._cur = self._conn.cursor()
        if params is None:
            self._cur.execute(translated)
        else:
            self._cur.execute(translated, params)
        return self

    def executemany(self, sql: str, seq: Any) -> None:
        translated = _translate_qmarks(sql)
        with self._conn.cursor() as cur:
            cur.executemany(translated, seq)

    def fetchone(self) -> Any:
        if self._cur is None:
            return None
        return self._cur.fetchone()

    def fetchall(self) -> list[Any]:
        if self._cur is None:
            return []
        return list(self._cur.fetchall())

    @property
    def description(self) -> Any:
        return self._cur.description if self._cur else None

    @property
    def lastrowid(self) -> Any:
        if self._cur is None:
            return None
        return self._cur.rownumber  # psycopg3 no expone lastrowid directamente

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        if self._cur:
            try:
                self._cur.close()
            except Exception:
                pass
        self._conn.close()

    def __enter__(self) -> _PgConnAdapter:
        return self

    def __exit__(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Pool Postgres (psycopg_pool.ConnectionPool)
# ---------------------------------------------------------------------------

_pg_pool: Any = None  # psycopg_pool.ConnectionPool | None
_pg_pool_lock = threading.Lock()


def _pg_connect_kwargs() -> dict[str, Any]:
    """Parámetros libpq extra aplicados a cada conexión del pool Postgres.

    - ``options``: ``statement_timeout`` + ``idle_in_transaction_session_timeout``
      server-side. Evitan que una query descontrolada u hostil, o una transacción
      idle, claven una conexión del (pequeño) pool y lo saturen (DoS barato).
    - ``connect_timeout``: no colgar indefinidamente si el pooler no responde.
    - ``sslrootcert``: CA raíz para ``sslmode=verify-full`` (si está configurada).
    """
    kwargs: dict[str, Any] = {}
    stmt_ms = int(getattr(settings, "DB_STATEMENT_TIMEOUT_MS", 30_000))
    idle_ms = int(getattr(settings, "DB_IDLE_TX_TIMEOUT_MS", 60_000))
    opts: list[str] = []
    if stmt_ms > 0:
        opts.append(f"-c statement_timeout={stmt_ms}")
    if idle_ms > 0:
        opts.append(f"-c idle_in_transaction_session_timeout={idle_ms}")
    if opts:
        kwargs["options"] = " ".join(opts)
    connect_timeout = int(getattr(settings, "DB_CONNECT_TIMEOUT", 10))
    if connect_timeout > 0:
        kwargs["connect_timeout"] = connect_timeout
    ca = getattr(settings, "DATABASE_SSL_ROOT_CERT", "") or ""
    if isinstance(ca, str) and ca.strip():
        kwargs["sslrootcert"] = ca.strip()
    return kwargs


def _get_pg_pool() -> Any:
    """Devuelve (creando si es necesario) el pool de conexiones Postgres."""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pg_pool_lock:
        if _pg_pool is not None:
            return _pg_pool
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError(
                "psycopg-pool no instalado. Ejecuta: pip install psycopg-pool>=3.2,<4"
            ) from exc

        pool_size = getattr(settings, "DB_POOL_SIZE", 5)
        conn_kwargs = _pg_connect_kwargs()
        try:
            _pg_pool = ConnectionPool(
                conninfo=_database_url(),
                min_size=1,
                max_size=max(pool_size, 2),
                kwargs=conn_kwargs,
                open=True,
            )
        except Exception as exc:
            # No filtrar el DSN (con password) en el mensaje de error propagado.
            from observability.logging import redact_dsn

            raise RuntimeError(
                f"No se pudo crear el pool Postgres: {redact_dsn(str(exc))}"
            ) from None
        log.info(
            "pg_pool_created",
            min=1,
            max=max(pool_size, 2),
            timeouts=conn_kwargs.get("options", "none"),
            ssl_ca=bool(conn_kwargs.get("sslrootcert")),
        )
    return _pg_pool


def _close_pg_pool() -> None:
    """Cierra el pool Postgres si está abierto."""
    global _pg_pool
    with _pg_pool_lock:
        pool = _pg_pool
        _pg_pool = None
    if pool is not None:
        try:
            pool.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Estado global del pool SQLite/Turso
# ---------------------------------------------------------------------------

_local = threading.local()

# Override para tests: si se setea, _get_conn() usa esta ruta en vez de settings.DB_PATH.
# Esto evita el patrón frágil de importlib.reload() en los tests.
_DB_PATH_OVERRIDE: str | None = None

# Pool de conexiones Turso (Queue thread-safe). Sólo se usa cuando hay
# TURSO_DATABASE_URL configurada (>1 conexión). Para SQLite local, thread-local basta.
_pool: _queue_mod.Queue[Any] | None = None
_pool_lock = threading.Lock()
_pool_active: int = 0  # conexiones vivas (idle en queue + en uso)

# Bandera de inicialización: evita ejecutar init_db() más de una vez por proceso.
# db.schema.init_db() la pone a True; set_db_path_override() la resetea.
_db_initialized = False


def set_db_path_override(path: str | None) -> None:
    """Establece (o limpia con None) el override de ruta de BD para tests."""
    global _DB_PATH_OVERRIDE, _db_initialized
    _DB_PATH_OVERRIDE = path
    _db_initialized = False  # fuerza re-init en la nueva ruta


# ---------------------------------------------------------------------------
# Heurísticas de backend SQLite/Turso
# ---------------------------------------------------------------------------


def is_turso_backend() -> bool:
    """Indica si la conexión activa apunta a Turso/Hrana (cloud o réplica).

    Centraliza la heurística usada en múltiples puntos del módulo. Devuelve
    ``False`` cuando hay un override de ruta de tests o cuando faltan
    credenciales de Turso (en cuyo caso se usa SQLite local).

    Importante: el protocolo Hrana no soporta sentencias ``PRAGMA``; usar
    esta función para decidir si emitirlas o no.
    """
    if is_postgres_backend():
        return False  # Postgres tiene precedencia
    return bool(
        not _DB_PATH_OVERRIDE
        and settings.TURSO_DATABASE_URL
        and settings.TURSO_AUTH_TOKEN.get_secret_value()
    )


def safe_pragma(conn: Any, stmt: str) -> None:
    """Ejecuta un ``PRAGMA`` solo si el backend lo soporta (SQLite local).

    No-op en Turso/Hrana y en Postgres. Cualquier excepción se silencia
    (defensive): los PRAGMAs son optimizaciones, no deben romper la operación.
    """
    if is_turso_backend() or is_postgres_backend():
        return
    try:
        conn.execute(stmt)
    except Exception:
        log.debug("safe_pragma_failed", extra={"stmt": stmt})


# Whitelist de identificadores SQL válidos: solo alfanuméricos y guiones bajos.
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(name: str) -> str:
    """Valida que ``name`` sea un identificador SQL seguro (previene inyección)."""
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(f"Identificador SQL no válido: {name!r}")
    return name


def get_table_columns(conn: Any, table: str) -> set[str]:
    """Devuelve el conjunto de nombres de columna de ``table``.

    Funciona en SQLite local (``PRAGMA table_info``), Turso/Hrana (fallback a
    ``SELECT * … LIMIT 0`` + ``cursor.description``) y Postgres (mismo fallback).
    Devuelve conjunto vacío si la tabla no existe o no se puede inspeccionar.

    Raises:
        ValueError: si ``table`` contiene caracteres no válidos.
    """
    _validate_identifier(table)

    if is_postgres_backend():
        # En Postgres usamos information_schema (más fiable que PRAGMA)
        try:
            cur = conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
                (table,),
            )
            rows = cur.fetchall()
            if rows:
                return {r[0] for r in rows}
        except Exception:
            pass
        # Fallback: SELECT * LIMIT 0
        try:
            cur = conn.execute(f"SELECT * FROM {table} LIMIT 0")
            if cur.description:
                return {d[0] for d in cur.description}
        except Exception:
            pass
        return set()

    # Intento 1: PRAGMA table_info (rápido en SQLite local)
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if rows:
            return {r[1] for r in rows}
    except Exception:
        pass

    # Intento 2: cursor.description (Turso/Hrana, o PRAGMA devolvió vacío)
    try:
        cur = conn.execute(f"SELECT * FROM {table} LIMIT 0")
        if cur.description:
            return {d[0] for d in cur.description}
    except Exception:
        pass

    return set()


# ---------------------------------------------------------------------------
# Creación y ciclo de vida de conexiones
# ---------------------------------------------------------------------------


def _create_pg_connection() -> _PgConnAdapter:
    """Crea una nueva conexión Postgres via psycopg_pool."""
    pool = _get_pg_pool()
    raw_conn = pool.getconn()
    return _PgConnAdapter(raw_conn)


def _return_pg_connection(adapter: _PgConnAdapter) -> None:
    """Devuelve la conexión subyacente al pool Postgres."""
    pool = _pg_pool
    if pool is not None:
        try:
            pool.putconn(adapter._conn)
        except Exception:
            try:
                adapter._conn.close()
            except Exception:
                pass


def _create_sqlite_connection() -> Any:
    """Crea una nueva conexión a la BD SQLite/Turso según la configuración actual.

    ``libsql`` (~15-25 MB RSS) se importa lazy aquí: en prod con backend
    Postgres (DATABASE_URL, precedencia máxima) esta función nunca se llama,
    así que el import no debe pagarse en cada arranque del proceso.
    """
    import libsql

    if is_turso_backend():
        return libsql.connect(
            settings.TURSO_DATABASE_URL, auth_token=settings.TURSO_AUTH_TOKEN.get_secret_value()
        )

    if (
        not _DB_PATH_OVERRIDE
        and os.environ.get("CI", "").lower() in ("1", "true", "yes")
        and not os.environ.get("PYTEST_CURRENT_TEST")
        and not is_postgres_backend()
    ):
        raise RuntimeError(
            "Faltan TURSO_DATABASE_URL / TURSO_AUTH_TOKEN / DATABASE_URL en el entorno CI. "
            "Configura los secrets del repositorio antes de ejecutar el pipeline."
        )
    db_path = _DB_PATH_OVERRIDE or str(settings.DB_PATH)
    conn = libsql.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    return conn


# Alias para compatibilidad con el código existente
_create_connection = _create_sqlite_connection


def _health_check(conn: Any) -> bool:
    """Verifica que una conexión sigue viva."""
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def _get_conn() -> Any:
    """Devuelve una conexión reutilizada por hilo.

    Para Postgres: usa psycopg_pool (pool gestionado).
    Para Turso cloud: pool interno con health-check.
    Para SQLite local: thread-local (1 conexión por hilo, WAL permite lecturas concurrentes).
    """
    global _pool, _pool_active

    # ── Postgres (precedencia máxima) ─────────────────────────────────────
    if is_postgres_backend():
        return _create_pg_connection()

    # ── Turso con pool_size > 1 ───────────────────────────────────────────
    if is_turso_backend() and settings.DB_POOL_SIZE > 1:
        if _pool is None:
            with _pool_lock:
                if _pool is None:
                    _pool = _queue_mod.Queue(maxsize=settings.DB_POOL_SIZE)
        # 1. Intentar obtener una conexión idle (no bloqueante)
        try:
            conn = _pool.get_nowait()
            if _health_check(conn):
                return conn
            # Conexión muerta — descontar y crear nueva abajo
            with _pool_lock:
                _pool_active -= 1
            try:
                conn.close()
            except Exception:
                pass
        except _queue_mod.Empty:
            pass

        # 2. Si no hay idle, intentar crear una nueva si no alcanzamos el límite
        with _pool_lock:
            if _pool_active < settings.DB_POOL_SIZE:
                _pool_active += 1
                create_new = True
            else:
                create_new = False

        if create_new:
            return _create_sqlite_connection()

        # 3. Pool lleno — esperar a que alguien devuelva una conexión
        acquire_timeout = getattr(settings, "DB_POOL_TIMEOUT", 10.0)
        try:
            conn = _pool.get(timeout=acquire_timeout)
            if _health_check(conn):
                return conn
            try:
                conn.close()
            except Exception:
                pass
            return _create_sqlite_connection()
        except _queue_mod.Empty:
            log.warning(
                "db_pool_acquire_timeout",
                pool_size=settings.DB_POOL_SIZE,
                timeout_s=acquire_timeout,
            )
            from observability.runtime_metrics import db_pool_acquire_timeout_total

            db_pool_acquire_timeout_total.inc()
            raise RuntimeError(
                f"No se pudo obtener una conexión DB del pool en {acquire_timeout}s. "
                "El pool está saturado. Considera aumentar DB_POOL_SIZE."
            ) from None

    # ── SQLite local / tests: thread-local ────────────────────────────────
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    conn = _create_sqlite_connection()
    _local.conn = conn
    return conn


def _return_conn(conn: Any) -> None:
    """Devuelve una conexión al pool (Turso/Postgres) o la mantiene en thread-local."""
    global _pool_active

    # Postgres: devolver al psycopg_pool
    if isinstance(conn, _PgConnAdapter):
        _return_pg_connection(conn)
        return

    if not (is_turso_backend() and settings.DB_POOL_SIZE > 1):
        return
    with _pool_lock:
        pool = _pool
    if pool is None:
        # Pool fue cerrado por close_pool(); cerrar la conexión huérfana.
        try:
            conn.close()
        except Exception:
            pass
        return
    try:
        pool.put_nowait(conn)
    except _queue_mod.Full:
        with _pool_lock:
            _pool_active -= 1
        try:
            conn.close()
        except Exception:
            pass


def close_pool() -> None:
    """Cierra la conexión del hilo actual y vacía el pool compartido."""
    global _pool, _pool_active

    # Postgres: cerrar el pool de psycopg_pool
    _close_pg_pool()

    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            log.debug("connection_close_failed")
        _local.conn = None

    # Vaciar pool compartido (Turso) — swap-then-drain para evitar race condition.
    # Adquirimos el lock solo para nullear _pool (impide nuevas conexiones),
    # luego drenamos fuera del lock para evitar deadlock.
    with _pool_lock:
        pool = _pool
        if pool is not None:
            _pool = None
            _pool_active = 0
    if pool is not None:
        while not pool.empty():
            try:
                c = pool.get_nowait()
                c.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Context managers públicos
# ---------------------------------------------------------------------------


@contextmanager
def connect() -> Iterator[Any]:
    """Context manager de escritura. Hace commit al salir, rollback en error.

    Instrumenta latencia de commit y errores SQLITE_BUSY (tripwires ADR-004).
    Los eventos se persisten en ops_events via buffer en memoria + flush
    best-effort (ver observability/ops_events.py).

    Con backend Postgres (ADR-016): usa psycopg_pool; el shim qmark→%s se
    aplica automáticamente en cada execute().
    """
    import time as _time

    from observability.ops_events import (
        _piggyback_flush,
        dec_writers,
        inc_writers,
        record_event,
        record_writers_high_if_needed,
    )
    from observability.runtime_metrics import (
        db_concurrent_writers,
        db_write_duration_seconds,
        sqlite_busy_errors_total,
    )

    conn = _get_conn()
    db_concurrent_writers.inc()
    n_writers = inc_writers()
    record_writers_high_if_needed(n_writers)
    try:
        yield conn
        t0 = _time.monotonic()
        conn.commit()
        dur = _time.monotonic() - t0
        db_write_duration_seconds.observe(dur)
        if dur > 0.5:
            record_event("write_slow", value=round(dur, 3))
        # Flush best-effort del buffer de ops_events piggyback al commit exitoso
        _piggyback_flush()
    except Exception as exc:
        _exc_str = str(exc).lower()
        if "busy" in _exc_str or "locked" in _exc_str:
            sqlite_busy_errors_total.inc()
            record_event("sqlite_busy", detail=str(exc)[:200])
        conn.rollback()
        raise
    finally:
        db_concurrent_writers.inc(-1)
        dec_writers()
        _return_conn(conn)


@contextmanager
def connect_read() -> Iterator[Any]:
    """Context manager de SOLO LECTURA.

    Con Postgres: mismo pool + ``SET LOCAL default_transaction_read_only = on``.
    Con Turso replica: conexión efímera a la réplica.
    Con SQLite local: delega en ``connect()`` con PRAGMA query_only.
    """
    if is_postgres_backend():
        conn = _get_conn()
        try:
            conn.execute("SET LOCAL default_transaction_read_only = on")
            yield conn
        finally:
            _return_conn(conn)
        return

    replica_url = settings.TURSO_REPLICA_URL
    if replica_url:
        try:
            import libsql_experimental as libsql_exp

            conn = libsql_exp.connect(
                replica_url,
                auth_token=settings.TURSO_AUTH_TOKEN.get_secret_value(),
            )
            try:
                yield conn
            finally:
                conn.close()
            return
        except ImportError:
            pass  # fallback to local connect

    # Fallback: usar pool normal (sin pragma para Turso/Hrana)
    conn = _get_conn()
    try:
        safe_pragma(conn, "PRAGMA query_only = ON")
        yield conn
    finally:
        safe_pragma(conn, "PRAGMA query_only = OFF")
        _return_conn(conn)
