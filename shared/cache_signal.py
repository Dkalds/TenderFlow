"""Señal de invalidación de caché entre el scraper y el dashboard.

Utiliza un archivo centinela (``DATA_DIR/.cache_invalidation``) cuyo
timestamp de modificación indica cuándo hubo una ingesta nueva. El
dashboard comprueba este timestamp antes de servir datos cacheados y,
si detecta que el archivo es más reciente que la última comprobación,
llama a ``invalidate_caches()`` para forzar la recarga.

Diseño deliberadamente simple (sin Redis, sin pubsub) para mantener la
arquitectura SQLite-first: un único archivo en disco es suficiente cuando
hay un solo nodo de scraper y un único proceso de dashboard.
"""

from __future__ import annotations

import time
from pathlib import Path

from observability.logging import get_logger

log = get_logger(__name__)

# Nombre del archivo centinela dentro de DATA_DIR
_SIGNAL_FILENAME = ".cache_invalidation"


def _signal_path() -> Path:
    from config import settings

    return settings.DATA_DIR / _SIGNAL_FILENAME


def signal_cache_invalidation() -> None:
    """Escribe/actualiza el archivo centinela con el timestamp actual.

    Debe llamarse al final de cada ingesta exitosa (``process_month``,
    ``update_daily``) para notificar al dashboard que los datos cambiaron.
    No lanza excepciones — si falla, solo loguea un warning.
    """
    try:
        path = _signal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()) + "\n", encoding="utf-8")
        log.debug("cache_signal_written", path=str(path))
    except Exception as exc:
        log.warning("cache_signal_write_failed", error=str(exc))


def check_cache_signal(last_check: float) -> bool:
    """Devuelve True si el archivo centinela fue modificado después de *last_check*.

    Args:
        last_check: Timestamp (``time.time()`` float) de la última comprobación.
                    Pasar ``0.0`` para forzar invalidación en la primera carga.

    Returns:
        True si hay datos nuevos y la caché debe invalidarse; False en caso contrario.
    """
    try:
        path = _signal_path()
        if not path.exists():
            return False
        mtime = path.stat().st_mtime
        return mtime > last_check
    except Exception as exc:
        log.warning("cache_signal_read_failed", error=str(exc))
        return False


def get_signal_timestamp() -> float:
    """Devuelve el timestamp del último signal, o 0.0 si no existe."""
    try:
        path = _signal_path()
        if not path.exists():
            return 0.0
        return path.stat().st_mtime
    except Exception:
        return 0.0
