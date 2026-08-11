"""Caché de proceso del clasificador SAP servido por la API.

Dos problemas que este módulo resuelve y que el singleton anterior
(``api/routes/licitaciones.py``) no:

1. **Carga duplicada.** El singleton comprobaba ``is None`` sin lock —su
   ``_classifier_lock_val = False`` era una variable muerta— así que dos
   peticiones concurrentes del threadpool podían entrar a la vez y hacer dos
   ``joblib.load()`` simultáneos, duplicando el pico de memoria en el mismo
   contenedor de 2 GiB donde ya hubo un OOM (ver ``api/app.py``, incidente de
   Render del 2026-08-02). El lock serializa la carga: quien llega segundo
   espera y reutiliza, en vez de cargar su propia copia.

2. **Activación sin efecto.** ``POST /models/{name}/activate/{version}``
   cambiaba ``is_active`` en la BD pero el proceso seguía sirviendo el modelo
   ya cargado hasta el siguiente reinicio, así que el rollback de modelo del
   runbook no surtía efecto. Ahora la ruta invalida esta caché, y el TTL cubre
   el caso multi-proceso (la activación llega a un worker; los demás recargan
   al vencer el TTL).
"""

from __future__ import annotations

import threading
import time
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_lock = threading.Lock()
_cached: Any = None
_loaded_at: float = 0.0


def _ttl_seconds() -> float:
    from config.settings import settings

    return float(getattr(settings, "API_MODEL_CACHE_TTL_SECONDS", 300.0))


def get_classifier() -> Any:
    """Devuelve el ``SAPClassifier`` activo, cargándolo si hace falta.

    La carga ocurre **con el lock tomado**: es más lento para el segundo hilo
    que llega, y es exactamente lo que se quiere frente a dos cargas paralelas
    del mismo artefacto en un contenedor con memoria contada.
    """
    global _cached, _loaded_at
    with _lock:
        ttl = _ttl_seconds()
        expired = ttl > 0 and (time.monotonic() - _loaded_at) >= ttl
        if _cached is None or expired:
            from scraper.ml_classifier import SAPClassifier

            _cached = SAPClassifier.load()
            _loaded_at = time.monotonic()
            log.info("classifier_cache_loaded", reason="expired" if expired else "cold")
        return _cached


def invalidate_classifier_cache() -> None:
    """Fuerza la recarga en la siguiente petición (tras activar otra versión)."""
    global _cached, _loaded_at
    with _lock:
        was_loaded = _cached is not None
        _cached = None
        _loaded_at = 0.0
    if was_loaded:
        log.info("classifier_cache_invalidated")
