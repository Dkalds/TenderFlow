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

    Si el almacén no está configurado no hay nada que purgar. Si falla, la
    purga del resto de tablas sigue su curso, pero el resultado lleva
    ``"error": -1`` y ``exigir_completa`` pone el paso en rojo después: tragarse
    el fallo dejaba el lock diario puesto y el bucket creciendo sin aviso.
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
        log.warning("retention_blobs_failed", error=str(exc), exc_info=True)
        resultado["error"] = -1
    log.info("retention_blobs", **resultado)
    return resultado


def _purgar_sesiones_caducadas() -> int:
    """Borra las sesiones revocadas o caducadas hace más de 30 días.

    El plazo vive en ``db.sessions.purge_expired_sessions`` (no es una regla de
    ``POLITICA_RETENCION``: una sesión no es un dato que se conserve por
    política, sino basura que la renovación deslizante ya no puede revivir).
    Sin esta llamada la tabla solo crecía. Fail-open, como la purga de binarios:
    devuelve ``-1`` si falla y el resto de la retención sigue.
    """
    try:
        from db.sessions import purge_expired_sessions

        borradas = purge_expired_sessions()
    except Exception as exc:
        log.warning("retention_sessions_failed", error=str(exc))
        return -1
    log.info("retention_sessions", borradas=borradas)
    return borradas


def run() -> dict[str, Any]:
    """Purga los datos históricos según la política de retención publicada.

    No pasa ningún plazo: los toma de `scheduler.retention.POLITICA_RETENCION`,
    que a su vez los lee de `RETENTION_*` en `config/settings.py`. Hasta 2026-09
    este job repetía los ocho números como literales, de modo que el job y el CLI
    podían divergir del documento que los publica sin que nada fallara.

    Raises:
        RetencionIncompleta: si alguna tabla (o las sesiones) anotó ``-1``,
            **después** de haber intentado todas. Así el cierre marca el paso
            en error y ``_run_periodic`` suelta el lock diario para que la
            pasada siguiente reintente, en vez de dar el día por purgado.
    """
    from scheduler.retention import exigir_completa, run_retention

    # ``run_retention`` devuelve ``dict[str, int]``; el desglose de binarios es
    # un dict anidado, así que el resultado del job se ensancha a ``Any``.
    resultado: dict[str, Any] = dict(run_retention(apply=True))
    resultado["documento_blobs"] = _purgar_binarios_expedientes_cerrados(apply=True)
    resultado["sessions"] = _purgar_sesiones_caducadas()
    exigir_completa(resultado)
    return resultado
