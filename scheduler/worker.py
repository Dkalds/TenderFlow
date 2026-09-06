"""Consumidor de la cola de trabajo — plan 2026-09 v2, S5.1 y S5.3.

Dos cosas viven aquí:

1. **Los handlers** de los tipos a demanda declarados en ``shared/jobs.py``.
   Están en ``scheduler/`` y no en ``shared/`` a propósito: tiran de
   ``services/``, ``scraper/`` y ``reportlab``, y ``shared/`` no importa hacia
   arriba. La API solo importa ``shared/jobs.py`` para encolar, así que jamás
   carga nada de esto.
2. **El bucle** que reclama, ejecuta y cierra jobs, más su arranque como hilo
   dentro del proceso ``APP_PROFILE=worker`` (ver ``api/app.py``).

Relación con ADR-012
--------------------
Esto **no es un plano de orquestación**. No hay cron, ni intervalos, ni
registry: el worker solo reacciona a lo que un usuario pidió. Los pasos
programados siguen siendo de GitHub Actions y este bucle ni siquiera los
reclama — ``claim`` filtra por ``TIPOS_A_DEMANDA``.

Vida del lock
-------------
``locked_at`` no se refresca mientras el handler corre: un job que tarde más
que ``JOBS_LOCK_TTL_SEGUNDOS`` (900 s por defecto) puede ser reclamado por otro
worker y ejecutarse dos veces. Los tres handlers son idempotentes —el upsert de
la ficha, el ``replace_chunks`` de los embeddings y el maquetado del PDF lo
son—, así que el peor caso es trabajo repetido, no dato corrupto. El TTL está
por encima del percentil alto de la extracción más larga; si algún tipo futuro
lo supera de forma sistemática, lo que toca es un heartbeat, no subir el TTL
hasta que un despliegue deje de recuperarse.
"""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
from types import FrameType
from typing import Any

from observability.logging import get_logger
from shared.jobs import (
    CACHE_EXPORTS,
    EXPORT_TTL_SEGUNDOS,
    Job,
    clave_cache_export,
    procesar_uno,
    reclamar_caducados,
    ruta_descarga_export,
)

log = get_logger(__name__)

# ── Handlers ────────────────────────────────────────────────────────────────


def ejecutar_ficha_pliego(job: Job) -> dict[str, Any]:
    """Extrae la ficha estructurada del pliego (el botón «Extraer ficha»).

    Delega en ``run_background_extraction``, que es el mismo cuerpo que corría
    como ``BackgroundTask`` y que **nunca lanza**: persiste el estado en
    ``tender_fact_sheets``, incluido el ``failed`` con detalle del caso «sin
    páginas». Aquí se relee esa fila y, si quedó en ``failed``, se lanza — que
    es la forma de decirle a la cola «esto merece un reintento», sin duplicar en
    este módulo la lógica de persistencia del servicio.
    """
    from services.rag.fact_sheet import get_fact_sheet, run_background_extraction

    licitacion_id = str(job.payload["licitacion_id"])
    run_background_extraction(
        licitacion_id,
        model=str(job.payload["model"]),
        budget_subject=job.payload.get("budget_subject"),
    )
    ficha = get_fact_sheet(licitacion_id)
    if ficha is None:
        raise RuntimeError(f"La extracción no dejó ficha para {licitacion_id!r}")
    if ficha.status == "failed":
        raise RuntimeError(ficha.error_detail or "La extracción de la ficha falló sin detalle")
    return {
        "licitacion_id": licitacion_id,
        "estado_ficha": ficha.status,
        "campos": ficha.field_count,
        "citas": ficha.evidence_count,
    }


def ejecutar_embeddings_expediente(job: Job) -> dict[str, Any]:
    """Chunkea y embebe los documentos de UN expediente.

    El cron nocturno (``scheduler/jobs/documentos_embeddings.py``) recorre la
    cola global por lotes; esto es lo mismo acotado al expediente que alguien
    tiene abierto ahora, que es el caso que el batch nocturno no cubre a tiempo.
    Reutiliza los métodos que ya existen en ``DocumentosRepository`` (ADR-022:
    no se escribe SQL nuevo fuera de ``db/``).
    """
    from db.repositories.documentos import DocumentosRepository
    from services.embeddings import embeddings_available, encode_texts
    from services.rag.chunking import chunk_text

    if not embeddings_available():
        # Sin el extra [ml-embeddings] no hay nada que hacer, y reintentarlo
        # tres veces no lo instalará: se cierra el job como hecho declarando
        # que no se procesó nada, en vez de dejar un `failed` que parece un bug.
        return {"licitacion_id": str(job.payload["licitacion_id"]), "documentos": 0, "chunks": 0}

    repo = DocumentosRepository()
    licitacion_id = str(job.payload["licitacion_id"])
    documentos = 0
    chunks_creados = 0
    for meta in repo.list_by_licitacion(licitacion_id):
        documento_id = int(meta["id"])
        if meta.get("status") != "extracted" or repo.count_chunks(documento_id) > 0:
            continue
        fila = repo.get(documento_id)
        texto = (fila or {}).get("texto")
        trozos = chunk_text(texto) if texto else []
        if not trozos:
            continue
        chunks_creados += repo.replace_chunks(documento_id, trozos, encode_texts(trozos))
        documentos += 1
    return {
        "licitacion_id": licitacion_id,
        "documentos": documentos,
        "chunks": chunks_creados,
    }


def ejecutar_export_pdf(job: Job) -> dict[str, Any]:
    """Maqueta el PDF de exportación fuera de la request.

    Hasta 50 000 filas y la maquetación de reportlab: segundos de CPU que en el
    threadpool de la API compiten con cada lectura del resto del producto.
    """
    from api.routes.exports import build_pdf_export
    from shared.cache import get_cache

    contenido, filas = build_pdf_export(job.payload)
    get_cache(CACHE_EXPORTS).set(clave_cache_export(job.id), contenido, ttl=EXPORT_TTL_SEGUNDOS)
    return {
        "filas": filas,
        "bytes": len(contenido),
        # `ruta_descarga_export` y no una cadena interpolada aquí: la ruta que
        # recoge el fichero es `/exports/descargas/{job_id}`. Publicar
        # `/exports/download?job_id=N` era peor que un enlace roto —esa ruta
        # IGNORA `job_id` (issue #50) y habría devuelto 200 con un PDF distinto,
        # el de los filtros por defecto—.
        "descarga": ruta_descarga_export(job.id),
    }


# ── Bucle ───────────────────────────────────────────────────────────────────


class Worker:
    """Bucle de consumo de la cola. Reutilizable como hilo o como proceso."""

    def __init__(
        self,
        *,
        worker_id: str | None = None,
        tipos: tuple[str, ...] | None = None,
        poll_segundos: float | None = None,
    ) -> None:
        from config.settings import jobs_worker_poll_segundos

        # El id identifica al consumidor en ``locked_by``. Con el hostname del
        # contenedor y el pid se distingue qué instancia tenía el job cuando un
        # despliegue la mató, que es la pregunta que se hace uno leyendo la cola.
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self.tipos = tipos
        self.poll_segundos = poll_segundos or jobs_worker_poll_segundos()
        self._parar = threading.Event()

    def detener(self) -> None:
        """Pide al bucle que termine tras el job en curso."""
        self._parar.set()

    @property
    def parado(self) -> bool:
        return self._parar.is_set()

    def procesar_tanda(self, *, maximo: int = 100) -> int:
        """Procesa hasta ``maximo`` jobs disponibles y devuelve cuántos hizo.

        Se detiene en cuanto la cola queda vacía. Es la unidad que consume el
        cierre de la pasada (S5.3): drena SU cola dentro del job de Actions y
        vuelve, sin quedarse esperando trabajo nuevo.
        """
        hechos = 0
        while hechos < maximo and not self._parar.is_set():
            job = procesar_uno(self.worker_id, tipos=self.tipos)
            if job is None:
                break
            hechos += 1
        return hechos

    def run_forever(self) -> None:
        """Consume hasta que alguien llame a :meth:`detener`.

        Un fallo de la cola misma (BD caída) no mata el bucle: se registra y se
        espera al siguiente ciclo. Matarlo dejaría el servicio vivo para el
        healthcheck de Render y mudo para la cola, que es el peor de los dos
        estados posibles.
        """
        log.info("worker_arrancado", worker_id=self.worker_id, tipos=self.tipos)
        ultima_barrida = 0.0
        while not self._parar.is_set():
            try:
                # La barrida de locks caducados va antes de reclamar: si un
                # despliegue acaba de matar a otra instancia, su trabajo vuelve
                # a la cola en el mismo ciclo en que este worker va a pedir.
                ahora = time.monotonic()
                if ahora - ultima_barrida >= self.poll_segundos * 10:
                    reclamar_caducados()
                    ultima_barrida = ahora
                if self.procesar_tanda(maximo=10) > 0:
                    continue
            except Exception as exc:
                log.warning("worker_ciclo_fallido", error=str(exc), exc_info=True)
            self._parar.wait(self.poll_segundos)
        log.info("worker_detenido", worker_id=self.worker_id)


def arrancar_en_hilo() -> Worker:
    """Arranca el bucle en un hilo daemon y devuelve el worker para pararlo.

    Lo usa el lifespan de ``api/app.py`` con ``APP_PROFILE=worker``: el proceso
    sirve ``/api/v1/health/ready`` (que es lo que sondea Render) mientras el
    hilo consume la cola.
    """
    worker = Worker()
    hilo = threading.Thread(target=worker.run_forever, name="tenderflow-worker", daemon=True)
    hilo.start()
    return worker


def main() -> int:
    """Entry point de ``python -m scheduler.worker`` (local y depuración).

    Instala el manejador de SIGTERM para que un ``docker stop`` o el despliegue
    de Render terminen el job en curso en vez de cortarlo a mitad; lo que no dé
    tiempo vuelve a la cola por TTL y lo termina el siguiente worker.
    """
    from db.database import init_db

    init_db()
    worker = Worker()

    def _parar(_sig: int, _frame: FrameType | None) -> None:
        log.info("worker_sigterm_recibido")
        worker.detener()

    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)
    worker.run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
