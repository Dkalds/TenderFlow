"""Rate limiting persistente en Postgres.

Complementa los controles de rate limit en memoria con un backend de base
de datos para que los lockouts de autenticación sobrevivan reinicios del
servidor y apliquen entre sesiones diferentes del mismo cliente.

Diseño:
  - Tabla ``rate_limits``: (key TEXT, ts REAL) — ventana deslizante de timestamps.
  - La clave incluye un identificador de cliente (IP o hash de sesión).
  - Limpieza automática de entradas expiradas en cada lectura.
"""

from __future__ import annotations

import time
from contextlib import AbstractContextManager
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


def _connect() -> AbstractContextManager[Any]:
    """Obtiene el context manager de conexión (lazy import para evitar ciclos)."""
    from db.database import connect

    return connect()


#: Segundos que se anuncian cuando no se pudo comprobar un lockout (fallo de la
#: BD o pool agotado). Se deniega igual, pero con un plazo corto: antes se
#: anunciaba la ventana entera (300 s), de modo que un pool agotado un momento
#: mandaba a todos los usuarios a esperar cinco minutos.
REINTENTO_SIN_COMPROBAR_S = 5.0


def check_rate_limit_db(
    key: str,
    *,
    max_calls: int = 5,
    window_seconds: float = 300.0,
) -> bool:
    """Verifica el rate limit persistido en la BD.

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
            conn.execute("DELETE FROM rate_limits WHERE key = %s AND ts < %s", [key, cutoff])
            row = conn.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE key = %s AND ts >= %s",
                [key, cutoff],
            ).fetchone()
            count = int(row[0])

            if count >= max_calls:
                return False

            conn.execute("INSERT INTO rate_limits (key, ts) VALUES (%s, %s)", [key, now])
            return True
    except Exception:
        # Si la tabla no existe o hay error de BD, denegar la operación (fail closed)
        log.warning("check_rate_limit_db_error", key=key, exc_info=True)
        return False


def record_failed_login(
    client_key: str,
    *,
    bucket: str = "login_fail",
    window_seconds: float = 300.0,
) -> int:
    """Registra un intento de login fallido y devuelve el conteo en la ventana.

    Args:
        client_key: Clave del cliente (e.g. hash de IP o session_id).

    Returns:
        Número de intentos fallidos en los últimos 5 minutos.
    """
    key = f"{bucket}:{client_key}"
    now = time.time()
    window = window_seconds
    cutoff = now - window

    try:
        with _connect() as conn:
            conn.execute("DELETE FROM rate_limits WHERE key = %s AND ts < %s", [key, cutoff])
            conn.execute("INSERT INTO rate_limits (key, ts) VALUES (%s, %s)", [key, now])
            row = conn.execute(
                "SELECT COUNT(*) FROM rate_limits WHERE key = %s AND ts >= %s",
                [key, cutoff],
            ).fetchone()
            return int(row[0])
    except Exception:
        log.debug("record_failed_login_db_error", client_key=client_key, exc_info=True)
        return 0


def is_login_locked_out(
    client_key: str,
    max_attempts: int = 5,
    *,
    bucket: str = "login_fail",
    window_seconds: float = 300.0,
) -> tuple[bool, float]:
    """Comprueba si un cliente está bloqueado por intentos fallidos.

    Args:
        client_key: Clave del cliente.
        max_attempts: Número de intentos fallidos antes del bloqueo.

    Returns:
        (bloqueado, segundos_restantes) — segundos_restantes=0.0 si no bloqueado.
    """
    key = f"{bucket}:{client_key}"
    window = window_seconds
    now = time.time()
    cutoff = now - window

    try:
        # Solo lee: por el pool de lectura, que no compite con las escrituras
        # (la auditoría, las sesiones) que un pico de logins fallidos satura.
        from db.database import connect_read

        with connect_read() as conn:
            rows = conn.execute(
                "SELECT ts FROM rate_limits WHERE key = %s AND ts >= %s ORDER BY ts DESC",
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
        # No permitir una caída de la tabla de límites como bypass de fuerza bruta.
        log.warning("is_login_lockout_db_error", client_key=client_key, exc_info=True)
        return True, REINTENTO_SIN_COMPROBAR_S


def fallos_recientes(
    client_key: str,
    *,
    bucket: str,
    window_seconds: float,
) -> tuple[int, float]:
    """``(fallos en la ventana, segundos desde el último)`` de un cubo de fallos.

    Para el contador de fallos **por cuenta** del login, que no bloquea: cuenta
    cuántos van y cuánto hace del último, y la ruta decide la pausa. Falla
    abierto (``(0, window_seconds)``): es una segunda defensa sobre el lockout
    por (IP, correo), que sí falla cerrado, y sin BD el login no funciona de
    todos modos.
    """
    key = f"{bucket}:{client_key}"
    now = time.time()
    try:
        from db.database import connect_read

        with connect_read() as conn:
            fila = conn.execute(
                "SELECT COUNT(*), MAX(ts) FROM rate_limits WHERE key = %s AND ts >= %s",
                [key, now - window_seconds],
            ).fetchone()
        if not fila or not fila[0]:
            return 0, window_seconds
        return int(fila[0]), max(0.0, now - float(fila[1]))
    except Exception:
        log.warning("fallos_recientes_db_error", bucket=bucket, exc_info=True)
        return 0, window_seconds


def clear_login_attempts(client_key: str, *, bucket: str = "login_fail") -> None:
    """Limpia los intentos fallidos de un cliente (tras login exitoso)."""
    key = f"{bucket}:{client_key}"
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM rate_limits WHERE key = %s", [key])
    except Exception:
        log.warning("clear_login_attempts_db_error", client_key=client_key)


def record_failed_mfa(user_id: int, *, window_seconds: float = 300.0) -> int:
    """Registra un fallo MFA por cuenta, compartido por todas sus sesiones."""
    return record_failed_login(f"user:{user_id}", bucket="mfa_fail", window_seconds=window_seconds)


def is_mfa_locked_out(
    user_id: int,
    *,
    max_attempts: int = 5,
    window_seconds: float = 300.0,
) -> tuple[bool, float]:
    """Comprueba el lockout MFA por cuenta y falla cerrado ante errores de BD."""
    return is_login_locked_out(
        f"user:{user_id}",
        max_attempts=max_attempts,
        bucket="mfa_fail",
        window_seconds=window_seconds,
    )


def clear_mfa_attempts(user_id: int) -> None:
    """Limpia fallos MFA solo después de una verificación satisfactoria."""
    clear_login_attempts(f"user:{user_id}", bucket="mfa_fail")


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
            cur = conn.execute("DELETE FROM rate_limits WHERE ts < %s", [cutoff])
            return int(cur.rowcount or 0)
    except Exception:
        log.debug("cleanup_expired_db_error", exc_info=True)
        return 0
