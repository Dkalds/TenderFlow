"""Caché de proceso del clasificador SAP servido por la API.

Tres problemas que este módulo resuelve y que el singleton anterior
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

3. **Un artefacto que la API no podía obtener** (revisión de arquitectura
   2026-09). Invalidar la caché solo sirve si al recargar se resuelve un
   artefacto *distinto*, y hasta ahora la recarga era ``SAPClassifier.load()``
   sin ruta: en Render eso mira ``data/models/sap_classifier.pkl``, un fichero
   que no existe —no hay disco, ``data/`` está fuera de la imagen y nadie
   llamaba a ``ensure_downloaded()`` salvo ``scraper/pipeline.py``—, así que
   ``/explain`` degradaba a 503 de forma permanente y el rollback no cambiaba
   nada de lo servido. Además había DOS resolvedores de la misma tabla
   ``model_versions``: este y ``shared.model_artifacts.resolve_active_artifact``,
   que sí descarga. Ahora **solo queda el segundo**, y su descarga aterriza en
   un directorio escribible (``shared.model_artifacts.artifact_cache_dir``).

Degradación visible
-------------------
Cuando el artefacto de la versión activa no se puede resolver, la API sigue
sirviendo lo que tenga a mano en vez de caerse — pero eso deja de ser un
detalle enterrado en un log: :func:`classifier_degradation` publica el motivo y
``SAPClassifier.explain`` lo adjunta al ``warning`` de su respuesta, que es
donde lo ve quien consume ``/explain``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

MODEL_NAME = "sap_classifier"

# Motivos de degradación publicados por :func:`classifier_degradation`.
# ``None`` = se está sirviendo el artefacto de la versión activa del registry.
DEGRADACION_SIN_VERSION_ACTIVA = "sin_version_activa"
DEGRADACION_REGISTRY_ILEGIBLE = "registry_ilegible"

_lock = threading.Lock()
_cached: Any = None
_loaded_at: float = 0.0
_degradado: str | None = None


def _ttl_seconds() -> float:
    from config.settings import settings

    return float(getattr(settings, "API_MODEL_CACHE_TTL_SECONDS", 300.0))


def _resolve_artifact(name: str) -> Path | None:
    """Resuelve el artefacto de la versión activa. Punto de inyección en tests.

    Envuelve ``shared.model_artifacts.resolve_active_artifact`` en una función
    de módulo para que los tests puedan sustituirla sin red ni BD: es la única
    dependencia externa de :func:`get_classifier`.
    """
    from shared.model_artifacts import resolve_active_artifact

    return resolve_active_artifact(name)


def _cargar() -> tuple[Any, str | None]:
    """``(clasificador, degradación)`` recién cargados desde el registry.

    Un ``ModelArtifactMismatch`` **propaga**: el fichero resuelto no es el que
    el registry dice, y servir explicaciones de otro modelo es peor que un 500.
    Cualquier otro fallo de resolución degrada al artefacto local, que es lo
    que se venía sirviendo — pero dejando dicho que es una degradación.
    """
    from scraper.ml_classifier import SAPClassifier
    from shared.model_artifacts import ModelArtifactMismatch

    artefacto: Path | None = None
    degradado: str | None = None
    try:
        artefacto = _resolve_artifact(MODEL_NAME)
        if artefacto is None:
            degradado = DEGRADACION_SIN_VERSION_ACTIVA
    except ModelArtifactMismatch:
        raise
    except Exception as exc:
        log.warning("classifier_cache_resolver_failed", error=str(exc))
        degradado = DEGRADACION_REGISTRY_ILEGIBLE

    clf = SAPClassifier.load(artefacto)
    if artefacto is not None:
        return clf, None
    # `load()` sin ruta consulta el registry por su cuenta y, si el path activo
    # no existe en esta máquina, sirve el local dejando su propio motivo
    # (`serving_version_mismatch`). Ese motivo es más preciso que el nuestro.
    return clf, (getattr(clf, "serving_degradado", None) or degradado)


def get_classifier() -> Any:
    """Devuelve el ``SAPClassifier`` activo, cargándolo si hace falta.

    La carga ocurre **con el lock tomado**: es más lento para el segundo hilo
    que llega, y es exactamente lo que se quiere frente a dos cargas paralelas
    del mismo artefacto en un contenedor con memoria contada.
    """
    global _cached, _loaded_at, _degradado
    with _lock:
        ttl = _ttl_seconds()
        expired = ttl > 0 and (time.monotonic() - _loaded_at) >= ttl
        if _cached is None or expired:
            _cached, _degradado = _cargar()
            _loaded_at = time.monotonic()
            log.info(
                "classifier_cache_loaded",
                reason="expired" if expired else "cold",
                degradado=_degradado,
            )
        return _cached


def classifier_degradation() -> str | None:
    """Por qué lo servido NO es el artefacto de la versión activa (o ``None``).

    Se lee **sin** forzar una carga: quien no haya pedido todavía el
    clasificador no debe pagar un ``joblib.load`` por preguntar.
    """
    with _lock:
        return _degradado


def invalidate_classifier_cache() -> None:
    """Fuerza la recarga en la siguiente petición (tras activar otra versión)."""
    global _cached, _loaded_at, _degradado
    with _lock:
        was_loaded = _cached is not None
        _cached = None
        _loaded_at = 0.0
        _degradado = None
    if was_loaded:
        log.info("classifier_cache_invalidated")
