"""Rate limiting persistente basado en SQLite.

Complementa ``dashboard/utils/rate_limit.py`` (session-based) con un backend
de base de datos para que los lockouts de autenticación sobrevivan reinicios
del servidor y apliquen entre sesiones diferentes del mismo cliente.

Diseño:
  - Tabla ``rate_limits``: (key TEXT, ts REAL) — ventana deslizante de timestamps.
  - La clave incluye un identificador de cliente (IP o hash de sesión).
  - Limpieza automática de entradas expiradas en cada lectura.
"""

from __future__ import annotations

import time

from observability.logging import get_logger

log = get_logger(__name__)


def _connect():  # type: ignore[no-untyped-def]
    """Obtiene el context manager de conexión (lazy import para evitar ciclos)."""
    from db.database import connect

    return connect()


def check_rate_limit_db(
    key: str,
    *,
    max_calls: int = 5,
    window_seconds: float = 300.0,
) -> bool:
    """Verifica el rate limit persistido en SQLite.

    Args:
        key: Identificador de la operación + cliente (e.g. "login:192.168.1.1").
        max_calls: Máximo de llamadas permitidas en la ventana.
        window_seconds: Tamaño de la ventana en segundos.

    Returns:
        True si la operación está dentro del límite, False si se excedió.
    """
    now = time.time()
    cutoff = now - window_seconds

    try:
        with _connect() as conn:
            conn.execute("DELETE FROM rate_limits WHERE key = ? AND ts < ?", [key, cutoff])
            row = conn.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE key = ? AND ts >= ?",
                [key, cutoff],
            ).fetchone()
            count = int(row[0])

            if count >= max_calls:
                return False

            conn.execute("INSERT INTO rate_limits (key, ts) VALUES (?, ?)", [key, now])
            return True
    except Exception:
        # Si la tabla no existe o hay error de BD, denegar la operación (fail closed)
        log.warning("check_rate_limit_db_error", key=key, exc_info=True)
        return False


def record_failed_login(client_key: str) -> int:
    """Registra un intento de login fallido y devuelve el conteo en la ventana.

    Args:
        client_key: Clave del cliente (e.g. hash de IP o session_id).

    Returns:
        Número de intentos fallidos en los últimos 5 minutos.
    """
    key = f"login_fail:{client_key}"
    now = time.time()
    window = 300.0  # 5 minutos
    cutoff = now - window

    try:
        with _connect() as conn:
            conn.execute("DELETE FROM rate_limits WHERE key = ? AND ts < ?", [key, cutoff])
            conn.execute("INSERT INTO rate_limits (key, ts) VALUES (?, ?)", [key, now])
            row = conn.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE key = ? AND ts >= ?",
                [key, cutoff],
            ).fetchone()
            return int(row[0])
    except Exception:
        log.debug("record_failed_login_db_error", client_key=client_key, exc_info=True)
        return 0


def is_login_locked_out(client_key: str, max_attempts: int = 5) -> tuple[bool, float]:
    """Comprueba si un cliente está bloqueado por intentos fallidos.

    Args:
        client_key: Clave del cliente.
        max_attempts: Número de intentos fallidos antes del bloqueo.

    Returns:
        (bloqueado, segundos_restantes) — segundos_restantes=0.0 si no bloqueado.
    """
    key = f"login_fail:{client_key}"
    window = 300.0  # 5 minutos
    now = time.time()
    cutoff = now - window

    try:
        with _connect() as conn:
            rows = conn.execute(
                "SELECT ts FROM rate_limits WHERE key = ? AND ts >= ? ORDER BY ts DESC",
                [key, cutoff],
            ).fetchall()
            count = len(rows)

            if count < max_attempts:
                return False, 0.0

            oldest_ts = float(rows[-1][0])
            expires_at = oldest_ts + window
            remaining = expires_at - now
            if remaining <= 0:
                return False, 0.0
            return True, remaining
    except Exception:
        log.debug("is_login_locked_out_db_error", client_key=client_key, exc_info=True)
        return False, 0.0


def clear_login_attempts(client_key: str) -> None:
    """Limpia los intentos fallidos de un cliente (tras login exitoso)."""
    key = f"login_fail:{client_key}"
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM rate_limits WHERE key = ?", [key])
    except Exception:
        log.warning("clear_login_attempts_db_error", client_key=client_key)


def cleanup_expired(window_seconds: float = 86_400.0) -> int:
    """Limpia todas las entradas expiradas de la tabla rate_limits.

    Diseñado para llamarse periódicamente (e.g. al inicio del scraper).

    Args:
        window_seconds: Entradas más antiguas que esto se eliminan (default: 24h).

    Returns:
        Número de filas eliminadas.
    """
    cutoff = time.time() - window_seconds
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM rate_limits WHERE ts < ?", [cutoff])
            # SQLite no tiene rowcount fiable vía libsql, así que devolvemos 0
            return 0
    except Exception:
        log.debug("cleanup_expired_db_error", exc_info=True)
        return 0
