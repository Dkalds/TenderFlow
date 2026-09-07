"""Cola de trabajo: tipos, encolado y ciclo de vida — plan 2026-09 v2, S5.1.

Qué resuelve
------------
El trabajo pesado que pide un usuario (extraer la ficha de un pliego, maquetar
un PDF grande, embeber los documentos de un expediente) corría en los
``BackgroundTasks`` del proceso de la API, con 30 s de drenado al apagar
(``api/app.py``). Un despliegue en mitad de una extracción la mataba. Aquí ese
trabajo se convierte en una fila de ``jobs`` que sobrevive al proceso: si el
worker muere, el lock caduca y otro lo termina.

Reparto de planos (D14)
-----------------------
- Lo que **pide un usuario** lo consume el worker de Render
  (``scheduler/worker.py``, ``APP_PROFILE=worker``): :data:`TIPOS_A_DEMANDA`.
- Lo **programado** sigue siendo de GitHub Actions, que es el único plano de
  cron (ADR-012). El cierre de la pasada encola sus pasos
  (:data:`TIPO_PASO_PIPELINE`) y **consume su propia cola dentro del job**, sin
  depender del worker ni introducir un segundo planificador.

La tabla es la misma para los dos; lo que separa los planos es el filtro de
``tipos`` al reclamar.

Qué NO es
---------
No es un sustituto de ``db/job_locks.py``. Aquel es un mutex con nombre y TTL
que ``scheduler/pipeline_runs.py::_run_periodic`` usa como ventana de cadencia
(el lock no se libera al terminar bien, y por eso el digest diario no sale seis
veces al día). Ver la nota de ``db/alembic/versions/v106_jobs.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from config.settings import (
    jobs_backoff_base_segundos,
    jobs_lock_ttl_segundos,
    jobs_max_intentos,
)
from db.repositories.jobs import JobsRepository
from observability.logging import get_logger

log = get_logger(__name__)

JobEstado = Literal["pending", "running", "done", "failed"]

# ── Tipos de job ────────────────────────────────────────────────────────────

#: Extracción de la ficha del pliego (``POST …/ficha-pliego/extract-async``).
TIPO_FICHA_PLIEGO = "ficha_pliego"
#: Chunking + embeddings de los documentos de UN expediente que alguien abrió.
TIPO_EMBEDDINGS_EXPEDIENTE = "embeddings_expediente"
#: Maquetado del PDF de exportación por encima del umbral de filas.
TIPO_EXPORT_PDF = "export_pdf"
#: Un paso del cierre post-ingesta (S5.4). No es trabajo a demanda: lo encola y
#: lo consume el propio job de Actions.
TIPO_PASO_PIPELINE = "paso_pipeline"


@dataclass(frozen=True)
class TipoJob:
    """Declaración de un tipo de job: quién lo ejecuta y cómo se deduplica.

    ``handler`` es una ruta ``modulo:funcion`` y no la función misma para que
    importar este módulo no arrastre el RAG, reportlab ni sentence-transformers:
    la API lo importa solo para encolar, y quien resuelve el handler es el
    consumidor (``scheduler/worker.py``). Es también lo que mantiene la
    dirección de las dependencias: ``shared/`` no importa ``services/``.

    ``clave_dedupe`` es el campo del payload que identifica el trabajo. Dos
    peticiones con el mismo valor y la organización de la primera todavía en
    cola no encolan dos veces — es el equivalente honesto del "ya está en curso"
    que antes vivía en una bandera de caché por proceso.
    """

    nombre: str
    handler: str
    clave_dedupe: str | None
    descripcion: str


#: Tipos que **pide un usuario** y consume el worker de Render.
TIPOS_A_DEMANDA: dict[str, TipoJob] = {
    TIPO_FICHA_PLIEGO: TipoJob(
        nombre=TIPO_FICHA_PLIEGO,
        handler="scheduler.worker:ejecutar_ficha_pliego",
        clave_dedupe="licitacion_id",
        descripcion="Extrae la ficha estructurada del pliego (descarga PDFs + LLM).",
    ),
    TIPO_EMBEDDINGS_EXPEDIENTE: TipoJob(
        nombre=TIPO_EMBEDDINGS_EXPEDIENTE,
        handler="scheduler.worker:ejecutar_embeddings_expediente",
        clave_dedupe="licitacion_id",
        descripcion="Chunkea y embebe los documentos de un expediente abierto.",
    ),
    TIPO_EXPORT_PDF: TipoJob(
        nombre=TIPO_EXPORT_PDF,
        handler="scheduler.worker:ejecutar_export_pdf",
        clave_dedupe=None,
        descripcion="Maqueta el PDF de exportación por encima del umbral de filas.",
    ),
}

#: Tipos del plano programado (Actions). Separados de los de arriba porque el
#: worker NO debe reclamarlos: si lo hiciera, el cierre de la pasada dependería
#: de que un servicio distinto estuviera vivo, y ADR-012 dice lo contrario.
TIPOS_PROGRAMADOS: dict[str, TipoJob] = {
    TIPO_PASO_PIPELINE: TipoJob(
        nombre=TIPO_PASO_PIPELINE,
        handler="scheduler.pipeline_runs:ejecutar_paso_encolado",
        clave_dedupe=None,
        descripcion="Un paso de CANONICAL_STEPS dentro del cierre de la pasada.",
    ),
}

TIPOS: dict[str, TipoJob] = {**TIPOS_A_DEMANDA, **TIPOS_PROGRAMADOS}


# ── Transporte del binario de un export ─────────────────────────────────────
#
# El resultado de un ``export_pdf`` no cabe en ``resultado_json``: es un PDF de
# hasta 50 000 filas. Viaja por la caché compartida —Redis en producción, que
# es obligatorio en el perfil `api` y también lo declara el worker—, que es el
# único almacén que ya comparten los dos procesos. Las dos puntas del cable
# viven aquí para que no puedan desincronizarse: el worker escribe
# (``scheduler/worker.py``) y la API lee (``api/routes/exports.py``).
#
# Con el backend en memoria (sin ``REDIS_URL``) worker y API solo se ven si son
# el mismo proceso. Por eso el umbral que activa este camino
# (``JOBS_EXPORT_UMBRAL_FILAS``) es alto y configurable: en un despliegue sin
# Redis, el camino síncrono sigue cubriendo todo lo que se pide de verdad.

#: Namespace de caché del binario de los exports encolados.
CACHE_EXPORTS = "exports"

#: Vida del PDF maquetado. Una hora es tiempo de sobra para que quien lo pidió
#: lo descargue, y evita que un export de 50 000 filas ocupe Redis para siempre.
EXPORT_TTL_SEGUNDOS = 3600


def clave_cache_export(job_id: int) -> str:
    """Clave del binario de un export dentro de :data:`CACHE_EXPORTS`."""
    return f"job:{job_id}"


#: Ruta con la que se recoge el PDF que dejó maquetado el worker. Vive aquí, y
#: no interpolada en el handler, porque quien la ESCRIBE (el worker, en el
#: ``resultado`` del job) y quien la SIRVE (``api/routes/exports.py``) son dos
#: procesos distintos: con la cadena repetida en los dos sitios, renombrar la
#: ruta dejaba al worker publicando una URL que ya no existía. Y el modo de
#: fallo no era un 404 — ``/exports/download?job_id=N`` responde **200 con otro
#: PDF**, el de los filtros por defecto, porque esa ruta ignora el parámetro a
#: propósito (issue #50). Un test comprueba que esta ruta existe en la app.
RUTA_DESCARGA_EXPORT = "/api/v1/exports/descargas/{job_id}"


def ruta_descarga_export(job_id: int) -> str:
    """URL desde la que se recoge el export encolado ``job_id``."""
    return RUTA_DESCARGA_EXPORT.format(job_id=job_id)


@dataclass(frozen=True)
class Job:
    """Una fila de ``jobs`` ya tipada."""

    id: int
    tipo: str
    payload: dict[str, Any]
    organization_id: int | None
    estado: JobEstado
    intentos: int
    run_after: datetime
    locked_by: str | None
    locked_at: datetime | None
    resultado: dict[str, Any] | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime


class JobDesconocido(ValueError):
    """El tipo pedido no está declarado en :data:`TIPOS`."""


def _cargar_json(crudo: str | None) -> dict[str, Any]:
    """Deserializa un campo JSON de la tabla, tolerando basura.

    ``Any`` en el valor es inevitable: el payload de cada tipo tiene una forma
    distinta y quien la conoce es su handler, no esta función.
    """
    if not crudo:
        return {}
    try:
        cargado = json.loads(crudo)
    except (TypeError, ValueError):
        return {}
    return cargado if isinstance(cargado, dict) else {}


#: Los mismos cuatro valores que el ``CHECK`` de ``v106_jobs``. Se recorren en
#: :func:`_a_estado` en vez de castear, porque un ``cast`` daría por bueno
#: cualquier texto que hubiera en la columna: si el vocabulario de la tabla y el
#: de este módulo divergieran, el fallo debe verse aquí y no tres capas después.
_ESTADOS: tuple[JobEstado, ...] = ("pending", "running", "done", "failed")


def _a_estado(valor: str) -> JobEstado:
    for estado in _ESTADOS:
        if estado == valor:
            return estado
    raise ValueError(f"Estado de job desconocido en la BD: {valor!r}")


def _a_job(fila: dict[str, Any]) -> Job:
    return Job(
        id=int(fila["id"]),
        tipo=str(fila["tipo"]),
        payload=_cargar_json(fila["payload_json"]),
        organization_id=None if fila["organization_id"] is None else int(fila["organization_id"]),
        estado=_a_estado(str(fila["estado"])),
        intentos=int(fila["intentos"]),
        run_after=fila["run_after"],
        locked_by=fila["locked_by"],
        locked_at=fila["locked_at"],
        resultado=_cargar_json(fila["resultado_json"]) if fila["resultado_json"] else None,
        error_detail=fila["error_detail"],
        created_at=fila["created_at"],
        updated_at=fila["updated_at"],
    )


_repo = JobsRepository()


# ── API pública de la cola ──────────────────────────────────────────────────


def enqueue(
    tipo: str,
    payload: dict[str, Any],
    *,
    organization_id: int | None = None,
    run_after: datetime | None = None,
    deduplicar: bool = True,
) -> int:
    """Encola un job y devuelve su id (o el del equivalente ya en cola).

    La deduplicación es un ``SELECT`` seguido de un ``INSERT`` y no un índice
    único: dos peticiones simultáneas pueden colarse ambas. El coste de esa
    carrera es una ejecución duplicada de un handler idempotente —el upsert de
    la ficha lo es— y a cambio dos organizaciones distintas que piden el mismo
    expediente siguen teniendo cada una SU job, que es lo que hace que
    ``GET /jobs/{id}`` pueda responder 404 por organización sin mentir.

    Raises:
        JobDesconocido: si el tipo no está declarado. Encolar un tipo que nadie
            sabe ejecutar dejaría una fila girando hasta agotar intentos.
    """
    declarado = TIPOS.get(tipo)
    if declarado is None:
        raise JobDesconocido(f"Tipo de job no declarado: {tipo!r}")

    if deduplicar and declarado.clave_dedupe:
        valor = payload.get(declarado.clave_dedupe)
        if valor is not None:
            existente = _repo.buscar_activo(
                tipo=tipo,
                campo=declarado.clave_dedupe,
                valor=str(valor),
                organization_id=organization_id,
                filtrar_organizacion=True,
            )
            if existente is not None:
                log.info("job_deduplicado", tipo=tipo, job_id=int(existente["id"]))
                return int(existente["id"])

    job_id = _repo.insertar(
        tipo=tipo,
        payload_json=json.dumps(payload, ensure_ascii=False, default=str),
        organization_id=organization_id,
        run_after=run_after,
    )
    log.info("job_encolado", tipo=tipo, job_id=job_id, organization_id=organization_id)
    return job_id


def claim(worker_id: str, *, tipos: tuple[str, ...] | None = None) -> Job | None:
    """Reclama un job para este consumidor, o ``None`` si no hay trabajo.

    ``tipos`` por defecto son los de :data:`TIPOS_A_DEMANDA`: el worker no toca
    los pasos programados (ADR-012). Pasar la tupla explícitamente es lo que
    hace el cierre de la pasada para consumir la suya.
    """
    fila = _repo.reclamar(
        worker_id=worker_id,
        tipos=tuple(TIPOS_A_DEMANDA) if tipos is None else tipos,
    )
    return _a_job(fila) if fila else None


def ack(job_id: int, resultado: dict[str, Any] | None = None) -> None:
    """Cierra el job como ``done`` con su resultado."""
    _repo.marcar_terminado(
        job_id,
        resultado_json=(
            None if resultado is None else json.dumps(resultado, ensure_ascii=False, default=str)
        ),
    )
    log.info("job_terminado", job_id=job_id)


def fail(job_id: int, error: str, *, intentos: int, terminal: bool = False) -> JobEstado:
    """Registra el fallo: reintento con backoff, o ``failed`` definitivo.

    ``intentos`` es el contador que ya lleva la fila (se incrementó al
    reclamar), así que el tercer fallo de un job con ``JOBS_MAX_INTENTOS=3`` es
    terminal.

    ``terminal=True`` salta el backoff. Lo usa el cierre post-ingesta (S5.4):
    sus pasos corren dentro de un job de Actions con presupuesto de 55 minutos,
    así que esperar 30 s y 60 s para reintentar un paso roto se comería la
    ventana de los que aún no han corrido. Un paso fallido lo reintenta la
    pasada siguiente, cuatro horas después, que es el comportamiento que el
    cierre ya tenía.

    Returns:
        El estado en el que queda el job: ``"pending"`` o ``"failed"``.
    """
    if terminal or intentos >= jobs_max_intentos():
        _repo.marcar_fallido(job_id, error_detail=error)
        log.warning("job_fallido_definitivo", job_id=job_id, intentos=intentos, error=error[:200])
        return "failed"

    espera = jobs_backoff_base_segundos() * (2 ** max(0, intentos - 1))
    proximo = datetime.now(UTC) + timedelta(seconds=espera)
    _repo.reprogramar(job_id, error_detail=error, run_after=proximo)
    log.info("job_reprogramado", job_id=job_id, intentos=intentos, espera_segundos=espera)
    return "pending"


def reclamar_caducados(*, ttl_segundos: int | None = None) -> list[int]:
    """Devuelve a ``pending`` los jobs cuyo worker dejó de dar señales."""
    devueltos = _repo.reclamar_caducados(
        ttl_segundos=jobs_lock_ttl_segundos() if ttl_segundos is None else ttl_segundos
    )
    if devueltos:
        log.warning("jobs_lock_caducado_devueltos", ids=devueltos)
    return devueltos


def obtener(job_id: int) -> Job | None:
    """Job por id, sin filtro de organización (lo aplica la ruta)."""
    fila = _repo.obtener(job_id)
    return _a_job(fila) if fila else None


def job_activo(tipo: str, *, campo: str, valor: str) -> Job | None:
    """Job ``pending``/``running`` de ese tipo para ``campo=valor``, si lo hay.

    Es lo que lee ``GET …/ficha-pliego/estado``: el estado de la extracción es
    ahora una consulta a la cola y no una bandera en la caché del proceso, que
    era invisible desde cualquier otra instancia.
    """
    fila = _repo.buscar_activo(tipo=tipo, campo=campo, valor=valor)
    return _a_job(fila) if fila else None


def ejecutar(job: Job) -> dict[str, Any] | None:
    """Resuelve el handler declarado del tipo y lo ejecuta.

    El handler recibe el :class:`Job` entero —y no solo su payload— porque el
    resultado de alguno depende de su propio id: el PDF de exportación se
    guarda bajo una clave derivada del job, que es la que después publica
    ``resultado``. Las excepciones **se propagan**: quien decide entre reintento
    y ``failed`` es :func:`fail`, no el handler.
    """
    declarado = TIPOS.get(job.tipo)
    if declarado is None:
        raise JobDesconocido(f"Tipo de job no declarado: {job.tipo!r}")
    modulo_nombre, _, funcion_nombre = declarado.handler.partition(":")
    import importlib

    modulo = importlib.import_module(modulo_nombre)
    funcion: Callable[[Job], dict[str, Any] | None] = getattr(modulo, funcion_nombre)
    return funcion(job)


def procesar_uno(worker_id: str, *, tipos: tuple[str, ...] | None = None) -> Job | None:
    """Reclama, ejecuta y cierra un job. ``None`` si no había trabajo.

    Nunca lanza por un fallo del handler: el error se guarda en la fila, que es
    donde el usuario lo consulta. Sí propaga un fallo de la propia cola (BD
    caída), porque eso no es un job roto sino un consumidor que no puede seguir.
    """
    job = claim(worker_id, tipos=tipos)
    if job is None:
        return None
    try:
        resultado = ejecutar(job)
    except Exception as exc:
        fail(job.id, f"{type(exc).__name__}: {exc}", intentos=job.intentos)
        log.warning("job_handler_fallo", job_id=job.id, tipo=job.tipo, error=str(exc))
        return job
    ack(job.id, resultado)
    return job


__all__ = [
    "CACHE_EXPORTS",
    "EXPORT_TTL_SEGUNDOS",
    "RUTA_DESCARGA_EXPORT",
    "TIPOS",
    "TIPOS_A_DEMANDA",
    "TIPOS_PROGRAMADOS",
    "TIPO_EMBEDDINGS_EXPEDIENTE",
    "TIPO_EXPORT_PDF",
    "TIPO_FICHA_PLIEGO",
    "TIPO_PASO_PIPELINE",
    "Job",
    "JobDesconocido",
    "JobEstado",
    "TipoJob",
    "ack",
    "claim",
    "clave_cache_export",
    "ejecutar",
    "enqueue",
    "fail",
    "job_activo",
    "obtener",
    "procesar_uno",
    "reclamar_caducados",
    "ruta_descarga_export",
]
