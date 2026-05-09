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
from typing import Any


def _get_conn() -> Any:
    """Obtiene la conexión de BD activa (lazy import para evitar ciclos)."""
    from db.database import _get_conn as _db_get_conn

    return _db_get_conn()


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
        conn = _get_conn()
        # Limpiar entradas expiradas para esta clave
        conn.execute("DELETE FROM rate_limits WHERE key = ? AND ts < ?", [key, cutoff])
        # Contar llamadas en ventana
        row = conn.execute(
            "SELECT COUNT(*) FROM rate_limits WHERE key = ? AND ts >= ?",
            [key, cutoff],
        ).fetchone()
        count = int(row[0])

        if count >= max_calls:
            conn.commit()
            return False

        # Registrar esta llamada (sin IGNORE — la tabla usa AUTOINCREMENT id)
        conn.execute("INSERT INTO rate_limits (key, ts) VALUES (?, ?)", [key, now])
        conn.commit()
        return True
    except Exception:
        # Si la tabla no existe o hay error de BD, permitir la operación (fail open)
        return True


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
        conn = _get_conn()
        conn.execute("DELETE FROM rate_limits WHERE key = ? AND ts < ?", [key, cutoff])
        conn.execute("INSERT INTO rate_limits (key, ts) VALUES (?, ?)", [key, now])
        row = conn.execute(
            "SELECT COUNT(*) FROM rate_limits WHERE key = ? AND ts >= ?",
            [key, cutoff],
        ).fetchone()
        conn.commit()
        return int(row[0])
    except Exception:
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
        conn = _get_conn()
        rows = conn.execute(
            "SELECT ts FROM rate_limits WHERE key = ? AND ts >= ? ORDER BY ts DESC",
            [key, cutoff],
        ).fetchall()
        count = len(rows)
        conn.commit()

        if count < max_attempts:
            return False, 0.0

        # El bloqueo expira cuando el intento más antiguo de la ventana salga
        oldest_ts = float(rows[-1][0])
        expires_at = oldest_ts + window
        remaining = expires_at - now
        if remaining <= 0:
            return False, 0.0
        return True, remaining
    except Exception:
        return False, 0.0


def clear_login_attempts(client_key: str) -> None:
    """Limpia los intentos fallidos de un cliente (tras login exitoso)."""
    key = f"login_fail:{client_key}"
    try:
        conn = _get_conn()
        conn.execute("DELETE FROM rate_limits WHERE key = ?", [key])
        conn.commit()
    except Exception:
        pass


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
        conn = _get_conn()
        conn.execute("DELETE FROM rate_limits WHERE ts < ?", [cutoff])
        conn.commit()
        # SQLite no tiene rowcount fiable vía libsql, así que devolvemos 0
        return 0
    except Exception:
        return 0
