"""Buffer de eventos operativos con flush best-effort a BD.

Reemplaza los counters Prometheus (por-proceso, mueren con el proceso efimero
del scheduler en GH Actions) por persistencia en SQLite: la unica fuente de
verdad comun entre todos los planos de ejecucion.

Semantica de diseno:
- ``record_event`` NUNCA toca la BD, NUNCA falla, NUNCA bloquea.  Solo
  appendea al buffer en memoria (deque con maxlen=200).
- ``flush_events`` escribe el buffer en BD de forma best-effort: timeout
  corto, swallow total de errores, jamas hace DDL, jamas llama al
  ``connect()`` publico (evita recursion y contention).
- El primer ``record_event`` registra un ``atexit`` para el flush final
  (critico para GH Actions, que finaliza el proceso al terminar el job).
- ``connect()`` llama a ``_piggyback_flush()`` post-commit exitoso para
  amortizar el coste de apertura de conexion.

Los flags de cobertura de datos (``sin_prediccion``, ``sin_historico_*``)
no se emiten aqui; son senales de scoring, no de infraestructura.
"""

from __future__ import annotations

import atexit
import os
import threading
from collections import deque
from datetime import UTC, datetime
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Buffer en memoria
# ---------------------------------------------------------------------------

_buffer: deque[dict[str, Any]] = deque(maxlen=200)
_lock = threading.Lock()
_atexit_registered = False

# Rate-limiting para eventos de alta frecuencia (writers_high):
# solo se emite 1 vez por minuto como maximo.
_last_writers_high: float = 0.0
_WRITERS_HIGH_MIN_INTERVAL = 60.0  # segundos


def record_event(
    event_type: str,
    value: float | None = None,
    detail: str | None = None,
) -> None:
    """Agrega un evento al buffer en memoria.

    Thread-safe, nunca falla, nunca toca la BD.
    """
    global _atexit_registered
    ts = datetime.now(UTC).isoformat()
    plane = os.environ.get("SCHEDULER_PLANE", "")
    pid = os.getpid()
    entry: dict[str, Any] = {
        "ts": ts,
        "event_type": event_type,
        "value": value,
        "plane": plane or None,
        "pid": pid,
        "detail": detail,
    }
    with _lock:
        _buffer.append(entry)
        if not _atexit_registered:
            atexit.register(_atexit_flush)
            _atexit_registered = True


def _atexit_flush() -> None:
    """Flush registrado con atexit -- critico para procesos efimeros (GH Actions)."""
    flush_events()


def flush_events() -> None:
    """Escribe el buffer en BD de forma best-effort.

    - Conexion efimera propia (no usa el pool publico -- evita recursion).
    - busy_timeout corto (250ms): si hay contention, descarta y sigue.
    - Swallow total de errores.
    - Jamas hace DDL: si la tabla no existe, descarta y sale.
    - Jamas llama a connect() ni connect_read() de db.connection.
    """
    with _lock:
        if not _buffer:
            return
        rows = list(_buffer)
        _buffer.clear()

    if not rows:
        return

    try:
        # Import lazy para evitar ciclo de imports al arrancar.
        from db.connection import is_postgres_backend

        if is_postgres_backend():
            _flush_postgres(rows)
        else:
            _flush_sqlite(rows)
    except Exception:
        pass


def _flush_postgres(rows: list[dict[str, Any]]) -> None:
    """Escribe el buffer en Postgres con una conexion efimera propia.

    Antes esta funcion escribia SIEMPRE con ``libsql`` contra un fichero SQLite
    local, incluso con el backend en Postgres (ADR-016). En los jobs de GitHub
    Actions eso significaba volcar los eventos a un fichero del runner efimero
    que se descarta al terminar, mientras ``scheduler/healthcheck.py`` los
    buscaba en Supabase y siempre los veia vacios -- es decir, los tripwires de
    persistencia llevaban sin señal desde el cutover. Como ``flush_events``
    traga todos los errores, el fallo era invisible.
    """
    import psycopg

    from db.connection import _database_url

    # Conexion directa sin pool: flush_events puede llamarse desde atexit,
    # cuando el pool ya esta cerrado.
    with psycopg.connect(_database_url(), connect_timeout=5) as conn:
        conn.execute("SET statement_timeout = 2000")
        conn.cursor().executemany(
            "INSERT INTO ops_events (ts, event_type, value, plane, pid, detail) "
            "VALUES (%(ts)s, %(event_type)s, %(value)s, %(plane)s, %(pid)s, %(detail)s)",
            rows,
        )
        conn.commit()


def _flush_sqlite(rows: list[dict[str, Any]]) -> None:
    """Escribe el buffer en SQLite local (desarrollo y tests)."""
    import libsql

    from config import settings

    db_path = settings.DB_PATH
    if db_path is None:
        db_path = settings.DATA_DIR / "licitaciones.db"

    # Conexion directa sin pool -- timeout corto para no agravar la contention.
    conn = libsql.connect(str(db_path))
    try:
        conn.execute("PRAGMA busy_timeout = 250")
        conn.executemany(
            "INSERT INTO ops_events (ts, event_type, value, plane, pid, detail) "
            "VALUES (:ts, :event_type, :value, :plane, :pid, :detail)",
            rows,
        )
        conn.commit()
    except Exception:
        # Si la tabla no existe o hay cualquier error, descartamos en silencio.
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _piggyback_flush() -> None:
    """Llamado desde db.connection.connect() post-commit exitoso.

    No-op si el buffer esta vacio para no penalizar el path caliente.
    """
    with _lock:
        has_data = bool(_buffer)
    if has_data:
        flush_events()


# ---------------------------------------------------------------------------
# Helpers para db.connection
# ---------------------------------------------------------------------------

_writers_lock = threading.Lock()
_active_writers: int = 0


def inc_writers() -> int:
    """Incrementa el contador de escritores activos. Devuelve el nuevo valor."""
    global _active_writers
    with _writers_lock:
        _active_writers += 1
        return _active_writers


def dec_writers() -> None:
    """Decrementa el contador de escritores activos."""
    global _active_writers
    with _writers_lock:
        _active_writers = max(0, _active_writers - 1)


def record_writers_high_if_needed(n: int) -> None:
    """Emite evento writers_high si n > 3, rate-limited a 1/min."""
    global _last_writers_high
    if n <= 3:
        return
    import time

    now = time.monotonic()
    with _lock:
        if now - _last_writers_high < _WRITERS_HIGH_MIN_INTERVAL:
            return
        _last_writers_high = now
    record_event("writers_high", value=float(n))
