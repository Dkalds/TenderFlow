"""Señal de invalidación de caché entre el scraper y el API.

En producción la señal se persiste en el event log de Postgres, el medio que
sí comparten el scraper de GitHub Actions y el API de Render. Las lecturas se
memoizan brevemente para no convertir cada request HTTP en un round trip.

El archivo centinela ``DATA_DIR/.cache_invalidation`` se conserva como
fallback para desarrollo y para degradar de forma segura si Postgres no está
configurado o no está disponible.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from pydantic import SecretStr

from observability.logging import get_logger

log = get_logger(__name__)

# Nombre del archivo centinela dentro de DATA_DIR
_SIGNAL_FILENAME = ".cache_invalidation"
_SHARED_POLL_INTERVAL_SECONDS = 5.0

_shared_signal_ts = 0.0
_shared_last_poll = float("-inf")
_shared_signal_lock = threading.Lock()


def _signal_path() -> Path:
    from config import settings

    return settings.DATA_DIR / _SIGNAL_FILENAME


def _database_signal_enabled() -> bool:
    """Indica si este proceso tiene configurado el Postgres compartido."""
    if os.environ.get("DATABASE_URL"):
        return True

    from config import settings

    configured = settings.DATABASE_URL
    if isinstance(configured, SecretStr):
        return bool(configured.get_secret_value())
    # Los tests pueden sustituir el SecretStr por un str plano.
    return bool(configured)


def _write_local_signal(timestamp: float) -> None:
    path = _signal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{timestamp}\n", encoding="utf-8")
    log.debug("cache_signal_file_written", path=str(path))


def _get_local_signal_timestamp() -> float:
    try:
        path = _signal_path()
        if not path.exists():
            return 0.0
        return path.stat().st_mtime
    except Exception as exc:
        log.warning("cache_signal_file_read_failed", error=str(exc))
        return 0.0


def _get_shared_signal_timestamp() -> float:
    """Lee Postgres como máximo una vez por intervalo y proceso."""
    global _shared_last_poll, _shared_signal_ts

    if not _database_signal_enabled():
        return 0.0

    now = time.monotonic()
    if now - _shared_last_poll < _SHARED_POLL_INTERVAL_SECONDS:
        return _shared_signal_ts

    with _shared_signal_lock:
        now = time.monotonic()
        if now - _shared_last_poll < _SHARED_POLL_INTERVAL_SECONDS:
            return _shared_signal_ts
        try:
            from db.events import get_latest_cache_invalidation_timestamp

            _shared_signal_ts = get_latest_cache_invalidation_timestamp()
        except Exception as exc:
            log.warning("cache_signal_database_read_failed", error=str(exc))
        finally:
            _shared_last_poll = now
        return _shared_signal_ts


def _record_shared_signal(timestamp: float) -> None:
    """Escribe la señal compartida y actualiza la memoización local."""
    global _shared_last_poll, _shared_signal_ts

    if not _database_signal_enabled():
        return
    from db.events import append_cache_invalidation_event

    append_cache_invalidation_event()
    with _shared_signal_lock:
        _shared_signal_ts = timestamp
        _shared_last_poll = time.monotonic()


def _reset_signal_poll_cache() -> None:
    """Reinicia el estado de polling. Uso exclusivo en tests."""
    global _shared_last_poll, _shared_signal_ts
    with _shared_signal_lock:
        _shared_signal_ts = 0.0
        _shared_last_poll = float("-inf")


def signal_cache_invalidation() -> None:
    """Publica una invalidación compartida y actualiza el fallback local.

    Debe llamarse al final de cada ingesta exitosa (``process_month``,
    ``update_daily``) para notificar al API que los datos cambiaron.
    No lanza excepciones — si falla, solo loguea un warning.
    """
    timestamp = time.time()
    try:
        _record_shared_signal(timestamp)
    except Exception as exc:
        log.warning("cache_signal_database_write_failed", error=str(exc))
    try:
        _write_local_signal(timestamp)
    except Exception as exc:
        log.warning("cache_signal_file_write_failed", error=str(exc))


def check_cache_signal(last_check: float) -> bool:
    """Devuelve True si la señal compartida avanzó tras *last_check*.

    Args:
        last_check: Timestamp (``time.time()`` float) de la última comprobación.
                    Pasar ``0.0`` para forzar invalidación en la primera carga.

    Returns:
        True si hay datos nuevos y la caché debe invalidarse; False en caso contrario.
    """
    return get_signal_timestamp() > last_check


def get_signal_timestamp() -> float:
    """Devuelve el timestamp más reciente de Postgres o del fallback local."""
    return max(_get_shared_signal_timestamp(), _get_local_signal_timestamp())
