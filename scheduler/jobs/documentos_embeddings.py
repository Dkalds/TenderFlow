"""Job de pliegos: descarga+extracción (F7) + chunking+embeddings (F8).

Patrón ``scheduler/jobs/ml_predicciones.py::run_scoring`` — ``run()`` es un
callable zero-argumento registrado en ambos planos de orquestación (ADR-012):
``build_default_registry()`` (APScheduler/Docker) y su workflow dedicado
``.github/workflows/pliegos.yml`` (GitHub Actions, cron nocturno + dispatch)
— nunca corren activos a la vez contra la misma BD.

Fases independientes por corrida, todas fail-open a nivel de documento/
licitación (uno roto no aborta el resto del lote, mismo criterio que el
resto del scraper):

1. **Fetch**: documentos ``pending`` → ``scraper.document_fetcher.fetch_and_extract``.
2. **Embed**: documentos ``extracted`` sin chunks → ``services.rag.chunking.chunk_text``
   → ``services.embeddings.encode_texts`` → ``documento_chunks``.
3. **Facts**: licitaciones con páginas y sin ficha → extracción Pydantic
   verificable (solo cuando ``PLIEGO_FACTS_ENABLED=True``).
4. **Tech signal**: licitaciones con páginas y sin señal de tecnología
   vigente → ``services.tech_signal.score_documents`` (keywords) → fusión
   inmediata hacia ``ml_tecnologias`` para ese lote
   (``services.tech_signal.merge_doc_signals``).

Si el extra ``[ml-embeddings]`` no está instalado, la fase de embeddings se
salta con un warning (no rompe la fase de fetch, que solo necesita ``[pliegos]``).
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_FETCH_BATCH_SIZE = 50
_EMBED_BATCH_SIZE = 50
_FACTS_BATCH_SIZE = 10
_TECH_SIGNAL_BATCH_SIZE = 500


def _run_fetch_phase(limit: int = _FETCH_BATCH_SIZE) -> dict[str, int]:
    """Descarga + extrae texto de documentos ``pending``, por lotes."""
    from db.repositories.documentos import DocumentosRepository
    from observability.runtime_metrics import documentos_fetched_total
    from scraper.document_fetcher import fetch_and_extract

    repo = DocumentosRepository()
    pendientes = repo.list_pendientes(limit=limit)
    counts: dict[str, int] = {"extracted": 0, "error": 0}
    for doc in pendientes:
        try:
            status = fetch_and_extract(doc)
        except Exception as e:
            log.warning(
                "documentos_fetch_unexpected_error", documento_id=doc.get("id"), error=str(e)
            )
            status = "error"
        counts[status] = counts.get(status, 0) + 1
        documentos_fetched_total.labels(status=status).inc()
    return counts


def _run_embed_phase(limit: int = _EMBED_BATCH_SIZE) -> dict[str, int]:
    """Chunkea + embebe documentos ``extracted`` que aún no tienen chunks."""
    from db.repositories.documentos import DocumentosRepository
    from observability.runtime_metrics import documento_chunks_total
    from services.rag.chunking import chunk_text

    repo = DocumentosRepository()
    counts = {"documentos_procesados": 0, "chunks_creados": 0, "sin_texto": 0, "error": 0}

    candidatos = repo.list_extracted_without_chunks(limit=limit)
    if not candidatos:
        return counts

    from services.embeddings import embeddings_available, encode_texts

    if not embeddings_available():
        # sentence-transformers no instalado ([ml-embeddings] ausente) — se
        # comprueba ANTES del loop (embeddings_available() es una simple
        # comprobación de import, no dispara la carga del modelo) para no
        # contar cada documento del lote como "error" individualmente.
        log.warning("documentos_embed_phase_skipped_no_ml_extra")
        return counts

    for doc in candidatos:
        texto = doc.get("texto")
        chunks = chunk_text(texto) if texto else []
        if not chunks:
            counts["sin_texto"] += 1
            continue
        try:
            embeddings = encode_texts(chunks)
            n = repo.replace_chunks(doc["id"], chunks, embeddings)
        except Exception as e:
            log.warning("documentos_embed_failed", documento_id=doc["id"], error=str(e))
            counts["error"] += 1
            continue
        counts["documentos_procesados"] += 1
        counts["chunks_creados"] += n
        documento_chunks_total.inc(n)
    return counts


def _run_facts_phase(limit: int = _FACTS_BATCH_SIZE) -> dict[str, int]:
    """Extrae fichas tipadas; fail-open por licitación y con gate de gasto."""
    from config import settings

    counts = {"procesadas": 0, "needs_review": 0, "error": 0, "disabled": 0}
    if not settings.PLIEGO_FACTS_ENABLED:
        counts["disabled"] = 1
        return counts

    from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
    from services.rag.fact_sheet import EXTRACTION_VERSION, extract_fact_sheet
    from services.tech_signal import ingest_llm_technologies

    repo = TenderFactSheetsRepository()
    pendientes = repo.list_pending_licitaciones(extraction_version=EXTRACTION_VERSION, limit=limit)
    for licitacion_id in pendientes:
        try:
            record = extract_fact_sheet(
                licitacion_id,
                model=settings.PLIEGO_FACTS_MODEL,
            )
        except Exception as exc:
            counts["error"] += 1
            log.warning(
                "documentos_facts_failed",
                licitacion_id=licitacion_id,
                error=str(exc),
            )
            continue
        counts["procesadas"] += 1
        if record.status == "needs_review":
            counts["needs_review"] += 1
        try:
            ingest_llm_technologies(record)
        except Exception as exc:
            log.warning(
                "documentos_facts_tech_ingest_failed",
                licitacion_id=licitacion_id,
                error=str(exc),
            )
    return counts


def _run_tech_signal_phase(limit: int = _TECH_SIGNAL_BATCH_SIZE) -> dict[str, int]:
    """Puntúa (keywords) licitaciones con páginas extraídas y sin señal
    vigente, y funde de inmediato la señal de ese lote hacia
    ``ml_tecnologias``. Fail-open por licitación -- una puntuación rota no
    aborta el resto del lote (mismo patrón que ``_run_facts_phase``).
    """
    from db.repositories.documentos import DocumentosRepository
    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
    from observability.runtime_metrics import pliego_tech_signal_total
    from scraper.lineage import current_filter_version
    from services.tech_signal import merge_doc_signals, score_documents

    doc_repo = DocumentosRepository()
    signal_repo = TecnologiaPliegoRepository()
    signal_version = current_filter_version()
    counts = {"scored": 0, "no_signal": 0, "error": 0}

    pendientes = signal_repo.list_licitaciones_pending_signal(
        signal_version=signal_version, limit=limit
    )
    for licitacion_id in pendientes:
        try:
            pages = doc_repo.list_pages_by_licitacion(licitacion_id)
            scores = score_documents(pages)
            signal_repo.upsert_signals(
                licitacion_id,
                method="keywords",
                signal_version=signal_version,
                scores=scores,
            )
        except Exception as e:
            counts["error"] += 1
            pliego_tech_signal_total.labels(method="keywords", status="error").inc()
            log.warning("tech_signal_score_failed", licitacion_id=licitacion_id, error=str(e))
            continue
        status = "scored" if scores else "no_signal"
        counts[status] += 1
        pliego_tech_signal_total.labels(method="keywords", status=status).inc()

    if pendientes:
        merge_result = merge_doc_signals(licitacion_ids=pendientes)
        counts["merged"] = merge_result["licitaciones_merged"]
    return counts


def run() -> dict[str, Any]:
    """Entry point del job.

    Los límites por fase vienen de ``config.settings`` (PLIEGO_FETCH_BATCH /
    PLIEGO_EMBED_BATCH / PLIEGO_FACTS_BATCH / PLIEGO_TECH_SIGNAL_BATCH); las
    constantes de módulo ``_FETCH_BATCH_SIZE`` etc. quedan como default de
    cada función para quien las invoque directamente (tests, backfills
    manuales) sin pasar por aquí.
    """
    from config import settings

    fetch_result = _run_fetch_phase(limit=settings.PLIEGO_FETCH_BATCH)
    embed_result = _run_embed_phase(limit=settings.PLIEGO_EMBED_BATCH)
    facts_result = _run_facts_phase(limit=settings.PLIEGO_FACTS_BATCH)
    tech_signal_result = _run_tech_signal_phase(limit=settings.PLIEGO_TECH_SIGNAL_BATCH)
    log.info(
        "documentos_embeddings_job_done",
        fetch=fetch_result,
        embed=embed_result,
        facts=facts_result,
        tech_signal=tech_signal_result,
    )
    return {
        "fetch": fetch_result,
        "embed": embed_result,
        "facts": facts_result,
        "tech_signal": tech_signal_result,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
#
# Invocado por .github/workflows/pliegos.yml. La lógica vive aquí y no en un
# heredoc del YAML para que pase por ruff/mypy/tests como el resto del código.


def run_cli() -> int:
    """Corre el job y falla solo si el lote entero de fetch se cayó.

    Un PDF corrupto suelto es normal y esperado; que **todos** los documentos
    del lote fallen sin ninguno extraído señala un problema sistémico
    (SSRF/red/breaker abierto) que sí debe romper el workflow.
    """
    from db.database import init_db

    init_db()
    resumen = run()

    fetch = resumen["fetch"]
    if fetch.get("error") and not fetch.get("extracted"):
        log.error("documentos_embeddings_cli_batch_failed", fetch=fetch)
        return 1
    return 0


def report_cli() -> int:
    """Informa del estado de ``documentos``/``documento_chunks``."""
    from db.repositories.documentos import DocumentosRepository

    counts = DocumentosRepository().status_counts()
    log.info("documentos_estado", **counts)
    return 0


if __name__ == "__main__":
    import sys

    _cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if _cmd == "run":
        sys.exit(run_cli())
    elif _cmd == "report":
        sys.exit(report_cli())
    else:
        log.error(
            "documentos_embeddings_unknown_command",
            cmd=_cmd,
            usage="python -m scheduler.jobs.documentos_embeddings [run|report]",
        )
        sys.exit(2)
