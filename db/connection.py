"""Gestión del pool de conexiones SQLite / Turso (libSQL).

Este módulo centraliza toda la lógica de conexión: creación, pooling thread-safe,
context managers ``connect()`` / ``connect_read()``, y helpers de diagnóstico.
No contiene lógica de dominio ni DDL; esos residen en ``db.schema`` y ``db.upsert``.
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

import libsql

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
# Estado global del pool
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
# Heurísticas de backend
# ---------------------------------------------------------------------------


def is_turso_backend() -> bool:
    """Indica si la conexión activa apunta a Turso/Hrana (cloud o réplica).

    Centraliza la heurística usada en múltiples puntos del módulo. Devuelve
    ``False`` cuando hay un override de ruta de tests o cuando faltan
    credenciales de Turso (en cuyo caso se usa SQLite local).

    Importante: el protocolo Hrana no soporta sentencias ``PRAGMA``; usar
    esta función para decidir si emitirlas o no.
    """
    return bool(
        not _DB_PATH_OVERRIDE
        and settings.TURSO_DATABASE_URL
        and settings.TURSO_AUTH_TOKEN.get_secret_value()
    )


def safe_pragma(conn: Any, stmt: str) -> None:
    """Ejecuta un ``PRAGMA`` solo si el backend lo soporta (SQLite local).

    No-op en Turso/Hrana. Cualquier excepción se silencia (defensive): los
    PRAGMAs son optimizaciones, no deben romper la operación principal.
    """
    if is_turso_backend():
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

    Funciona tanto en SQLite local (``PRAGMA table_info``) como en
    Turso/Hrana (fallback a ``SELECT * … LIMIT 0`` + ``cursor.description``).
    Devuelve conjunto vacío si la tabla no existe o no se puede inspeccionar.

    Raises:
        ValueError: si ``table`` contiene caracteres no válidos.
    """
    _validate_identifier(table)

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


def _create_connection() -> Any:
    """Crea una nueva conexión a la BD según la configuración actual."""
    if is_turso_backend():
        return libsql.connect(
            settings.TURSO_DATABASE_URL, auth_token=settings.TURSO_AUTH_TOKEN.get_secret_value()
        )

    if (
        not _DB_PATH_OVERRIDE
        and os.environ.get("CI", "").lower() in ("1", "true", "yes")
        and not os.environ.get("PYTEST_CURRENT_TEST")
    ):
        raise RuntimeError(
            "Faltan TURSO_DATABASE_URL / TURSO_AUTH_TOKEN en el entorno CI. "
            "Configura los secrets del repositorio antes de ejecutar el pipeline."
        )
    db_path = _DB_PATH_OVERRIDE or str(settings.DB_PATH)
    conn = libsql.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    return conn


def _health_check(conn: Any) -> bool:
    """Verifica que una conexión sigue viva."""
    try:
        conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def _get_conn() -> Any:
    """Devuelve una conexión reutilizada por hilo.

    Para Turso cloud usa un pool con health-check. Para SQLite local usa
    thread-local (1 conexión por hilo, WAL permite lecturas concurrentes).
    """
    global _pool, _pool_active

    # Para Turso con pool_size > 1, usar el pool compartido
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
            return _create_connection()

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
            return _create_connection()
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

    # SQLite local / tests: thread-local (una conexión por hilo)
    conn = getattr(_local, "conn", None)
    if conn is not None:
        return conn
    conn = _create_connection()
    _local.conn = conn
    return conn


def _return_conn(conn: Any) -> None:
    """Devuelve una conexión al pool (Turso) o la mantiene en thread-local."""
    global _pool_active
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
    """Context manager de escritura. Hace commit al salir, rollback en error."""
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _return_conn(conn)


@contextmanager
def connect_read() -> Iterator[Any]:
    """Context manager de SOLO LECTURA.

    Si ``TURSO_REPLICA_URL`` está configurado, conecta a la réplica Turso
    (conexión efímera, sin pool). En caso contrario, delega en ``connect()``
    normal (misma BD, modo read-only via PRAGMA).
    """
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
