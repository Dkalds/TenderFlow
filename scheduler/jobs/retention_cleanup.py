"""Data retention cleanup — purge historical rows per policy.

Desde S8.1 la purga cubre también los **binarios** de los pliegos que
``shared/object_store.py`` conserva: sin esto, el bucket sólo crece. Va aquí y
no en ``scheduler/retention.py`` porque no es una tabla que se borre con un
``DELETE`` — hay que borrar en el almacén de objetos y sólo después olvidar la
clave en la fila, y ese orden importa (ver ``clear_blob_keys``).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

#: Un expediente cerrado deja de ser consultable como oportunidad, pero su
#: pliego sigue siendo evidencia útil para el análisis de mercado y para
#: reprocesar la ficha. Dos años es el horizonte que ya usan los cortes
#: competitivos del producto (``services/competitive/*`` mira 24 meses), así
#: que el binario deja de hacer falta a la vez que el expediente deja de
#: aparecer en ellos.
BLOBS_RETENTION_MESES = 24

#: Tope por corrida. La purga vive dentro del job nocturno y no puede comerse
#: su ventana: si hay más, el resto cae en la corrida siguiente.
_BLOBS_BATCH = 500


def _purgar_binarios_expedientes_cerrados(*, apply: bool = True) -> dict[str, int]:
    """Borra del almacén los binarios de expedientes cerrados hace >24 meses.

    Devuelve ``{"candidatos", "borrados", "claves_olvidadas"}``. Se cuenta
    —criterio de aceptación de S8.1— porque una purga que no dice cuánto purgó
    no se puede auditar: la diferencia entre ``candidatos`` y ``borrados`` es
    exactamente el número de claves que la fila conservaba y el bucket ya no
    tenía.

    Fail-open: si el almacén no está configurado o falla, se registra y la
    purga del resto de tablas sigue su curso.
    """
    resultado = {"candidatos": 0, "borrados": 0, "claves_olvidadas": 0}
    try:
        from db.repositories.documentos import DocumentosRepository
        from shared.object_store import get_object_store, purge_keys

        if not get_object_store().enabled:
            log.info("retention_blobs_sin_almacen")
            return resultado

        # ``timedelta`` no tiene meses, así que 24 meses se aproximan por 30
        # días. La imprecisión (±12 días sobre dos años) no cambia ninguna
        # decisión: el criterio es «hace mucho», no una fecha contractual.
        corte = (datetime.now(UTC) - timedelta(days=BLOBS_RETENTION_MESES * 30)).isoformat()
        repo = DocumentosRepository()
        filas = repo.list_blobs_de_expedientes_cerrados(corte, limit=_BLOBS_BATCH)
        resultado["candidatos"] = len(filas)
        if not filas or not apply:
            return resultado

        claves = [str(f["blob_key"]) for f in filas if f.get("blob_key")]
        resultado["borrados"] = purge_keys(claves)
        # Se olvida la clave de TODAS las filas candidatas, no sólo de las que
        # el bucket tenía: una clave cuyo objeto ya no existe es una referencia
        # muerta que volvería a salir candidata cada noche.
        resultado["claves_olvidadas"] = repo.clear_blob_keys(int(f["id"]) for f in filas)
    except Exception as exc:
        log.warning("retention_blobs_failed", error=str(exc))
    log.info("retention_blobs", **resultado)
    return resultado


def run() -> dict[str, Any]:
    """Purga los datos históricos según la política de retención publicada.

    No pasa ningún plazo: los toma de `scheduler.retention.POLITICA_RETENCION`,
    que a su vez los lee de `RETENTION_*` en `config/settings.py`. Hasta 2026-09
    este job repetía los ocho números como literales, de modo que el job y el CLI
    podían divergir del documento que los publica sin que nada fallara.
    """
    from scheduler.retention import run_retention

    # ``run_retention`` devuelve ``dict[str, int]``; el desglose de binarios es
    # un dict anidado, así que el resultado del job se ensancha a ``Any``.
    resultado: dict[str, Any] = dict(run_retention(apply=True))
    resultado["documento_blobs"] = _purgar_binarios_expedientes_cerrados(apply=True)
    return resultado
