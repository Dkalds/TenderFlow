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
   verificable (solo cuando ``PLIEGO_FACTS_ENABLED=True``). Una credencial
   rechazada (``LLMAuthError``) corta el lote en el primer rechazo, y un
   lote sin ninguna ficha útil pone el workflow en rojo (``run_cli``).
4. **Tech signal**: licitaciones con páginas y sin señal de tecnología
   vigente → ``services.tech_signal.score_documents`` (keywords) → fusión
   inmediata hacia ``ml_tecnologias`` para ese lote
   (``services.tech_signal.merge_doc_signals``).
5. **Resumen IA**: calienta el caché del resumen de las licitaciones que se
   van a abrir (seguidas, banda ``Caliente`` del score, publicadas hoy) si no
   tienen entrada vigente (solo con ``RESUMEN_PREGEN_ENABLED=True`` y caché
   compartida). Mismo corte por credencial rechazada que la fase 3, más el
   del presupuesto LLM.

Si el extra ``[ml-embeddings]`` no está instalado, la fase de embeddings se
salta con un warning (no rompe la fase de fetch, que solo necesita ``[pliegos]``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_FETCH_BATCH_SIZE = 50
_EMBED_BATCH_SIZE = 50
_FACTS_BATCH_SIZE = 10
_TECH_SIGNAL_BATCH_SIZE = 500
_RESUMEN_PREGEN_BATCH_SIZE = 20


def _run_fetch_phase(limit: int = _FETCH_BATCH_SIZE) -> dict[str, int]:
    """Descarga + extrae texto de documentos ``pending``, por lotes."""
    from db.repositories.documentos import DocumentosRepository
    from observability.runtime_metrics import documentos_fetched_total
    from scraper.document_fetcher import fetch_and_extract

    repo = DocumentosRepository()
    pendientes = repo.list_pendientes(limit=limit)
    # ``skipped`` (breaker abierto) y ``unsupported`` (formato que no sabemos
    # leer, S8.2) se declaran aquí para que el informe del cron tenga siempre la
    # misma forma: un lote entero saltado debe verse como 300 skipped, no como
    # una clave ausente.
    counts: dict[str, int] = {"extracted": 0, "error": 0, "skipped": 0, "unsupported": 0}
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


def _paginas_del_documento(repo: Any, documento_id: int) -> list[tuple[int, int]]:
    """`[(start_offset, page_number)]` del documento, o vacío si no hay páginas.

    Un fallo leyendo las páginas no puede tumbar el embedding: sin páginas los
    chunks se guardan igual y la cita apunta al documento en vez de a la página.
    """
    try:
        paginas = repo.list_pages(documento_id)
    except Exception:
        log.warning("documentos_embed_paginas_failed", documento_id=documento_id, exc_info=True)
        return []
    return [
        (int(p.get("start_offset") or 0), int(p["page_number"]))
        for p in paginas
        if p.get("page_number") is not None
    ]


def _embeber_documentos(
    repo: Any, candidatos: list[dict[str, Any]], counts: dict[str, int]
) -> None:
    """Chunkea, embebe y persiste cada documento del lote, con su versión."""
    from config.settings import settings
    from observability.runtime_metrics import documento_chunks_total
    from services.embeddings import encode_texts
    from services.rag.chunking import chunk_text_with_offsets, pagina_de_offset

    for doc in candidatos:
        texto = doc.get("texto")
        con_offset = chunk_text_with_offsets(texto) if texto else []
        if not con_offset:
            counts["sin_texto"] += 1
            continue
        chunks = [c for c, _ in con_offset]
        inicios = _paginas_del_documento(repo, doc["id"])
        paginas = [pagina_de_offset(off, inicios) if inicios else None for _, off in con_offset]
        try:
            embeddings = encode_texts(chunks)
            n = repo.replace_chunks(
                doc["id"],
                chunks,
                embeddings,
                embedding_model=settings.EMBEDDING_MODEL,
                embedding_version=settings.EMBEDDING_VERSION,
                paginas=paginas,
            )
        except Exception as e:
            log.warning("documentos_embed_failed", documento_id=doc["id"], error=str(e))
            counts["error"] += 1
            continue
        counts["documentos_procesados"] += 1
        counts["chunks_creados"] += n
        documento_chunks_total.inc(n)


def _run_embed_phase(limit: int = _EMBED_BATCH_SIZE) -> dict[str, int]:
    """Chunkea + embebe documentos ``extracted`` sin chunks o con versión vieja.

    El segundo grupo es el re-embedding de C5.7 y va **después** del primero: un
    documento sin ningún chunk no tiene retrieval en absoluto, mientras que uno
    con la versión anterior sí lo tiene (degradado, pero consistente). Poner el
    re-embedding delante dejaría a los documentos nuevos esperando detrás de una
    migración que puede durar días.
    """
    from config.settings import settings
    from db.repositories.documentos import DocumentosRepository

    repo = DocumentosRepository()
    counts = {
        "documentos_procesados": 0,
        "chunks_creados": 0,
        "sin_texto": 0,
        "error": 0,
        "reembebidos": 0,
    }

    candidatos = repo.list_extracted_without_chunks(limit=limit)
    obsoletos: list[dict[str, Any]] = []
    if len(candidatos) < limit and settings.EMBEDDING_VERSION:
        try:
            obsoletos = repo.documentos_con_embedding_obsoleto(
                settings.EMBEDDING_VERSION, limit=limit - len(candidatos)
            )
        except Exception:
            # La columna puede no existir aún (entorno sin v120). El job sigue
            # haciendo su trabajo normal en vez de caerse por el añadido.
            log.warning("documentos_embed_version_query_failed", exc_info=True)
    if not candidatos and not obsoletos:
        return counts

    from services.embeddings import embeddings_available

    if not embeddings_available():
        # sentence-transformers no instalado ([ml-embeddings] ausente) — se
        # comprueba ANTES del loop (embeddings_available() es una simple
        # comprobación de import, no dispara la carga del modelo) para no
        # contar cada documento del lote como "error" individualmente.
        log.warning("documentos_embed_phase_skipped_no_ml_extra")
        return counts

    _embeber_documentos(repo, candidatos, counts)
    antes = counts["documentos_procesados"]
    _embeber_documentos(repo, obsoletos, counts)
    counts["reembebidos"] = counts["documentos_procesados"] - antes
    return counts


def _run_facts_phase(limit: int = _FACTS_BATCH_SIZE) -> dict[str, Any]:
    """Extrae fichas tipadas; fail-open por licitación y con gate de gasto.

    La excepción es una credencial rechazada: ``LLMAuthError`` corta el lote en
    el primer rechazo, porque la misma key fallaría en todo lo que queda, y
    deja la causa en ``counts["credencial_rechazada"]`` para que ``run_cli`` la
    nombre en la alerta.
    """
    from config import settings

    # Any: contadores enteros más la causa textual de ``credencial_rechazada``.
    counts: dict[str, Any] = {"procesadas": 0, "needs_review": 0, "error": 0, "disabled": 0}
    if not settings.PLIEGO_FACTS_ENABLED:
        counts["disabled"] = 1
        return counts

    from db.repositories.tender_fact_sheets import TenderFactSheetsRepository
    from llm.providers import LLMAuthError
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
        except LLMAuthError as exc:
            # Del run #50 (2026-08-31) al #60 (2026-09-10) cada licitación del
            # lote repitió el mismo 401 y quedó con su ficha en `failed`, que la
            # manda al final de la cola de pendientes. Cortando aquí solo paga una.
            counts["error"] += 1
            counts["credencial_rechazada"] = str(exc)
            log.error(
                "documentos_facts_auth_rejected",
                licitacion_id=licitacion_id,
                pendientes_sin_procesar=len(pendientes) - counts["procesadas"],
                error=str(exc),
            )
            break
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


def facts_failed_systemically(counts: Mapping[str, object]) -> bool:
    """True si la fase de fichas no sirvió de nada por una causa común.

    Mismo criterio que ``llm_tech_labeling.batch_failed_systemically``: una
    ficha que el modelo no sabe extraer es normal y se cuenta como error
    suelto; que el lote entero falle sin dejar ni una ficha no lo es. Una
    credencial rechazada lo es siempre, aunque antes del rechazo se hubiera
    extraído alguna ficha: la corrida siguiente fallará entera con la misma key.
    """
    if counts.get("credencial_rechazada"):
        return True
    return bool(counts.get("error")) and not counts.get("procesadas")


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


def _ids_banda_caliente(limit: int) -> list[str]:
    """Top de la banda ``Caliente`` del score genérico (sin perfil de usuario).

    El score no tiene columna que leer —se calcula en
    ``services.analytics.scoring`` sobre el universo vivo—, así que esta fuente
    la pide el job al servicio en vez de a ``db/``.
    """
    from services.analytics.scoring import ScoringFilters, get_scoring

    resultado = get_scoring(ScoringFilters(band="Caliente", limit=limit))
    return [op.id_externo for op in resultado.opportunities]


def _candidatas_resumen(limit: int) -> list[str]:
    """Licitaciones a pre-resumir, por prioridad y sin repetir.

    Orden: seguidas (oportunidad abierta o favorita) → banda ``Caliente`` del
    score → publicadas hoy. Cada fuente es fail-open: si el scoring se cae, las
    seguidas y las de hoy se resumen igual.
    """
    from datetime import UTC, datetime

    from db.resumen_pregen import licitaciones_publicadas_desde, licitaciones_seguidas_abiertas

    inicio_de_hoy = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    fuentes: list[tuple[str, Callable[[], list[str]]]] = [
        ("seguidas", lambda: licitaciones_seguidas_abiertas(limit)),
        ("banda_caliente", lambda: _ids_banda_caliente(limit)),
        ("publicadas_hoy", lambda: licitaciones_publicadas_desde(inicio_de_hoy.isoformat(), limit)),
    ]
    vistas: dict[str, None] = {}
    for nombre, fuente in fuentes:
        if len(vistas) >= limit:
            break
        try:
            ids = fuente()
        except Exception as exc:
            log.warning("resumen_pregen_fuente_failed", fuente=nombre, error=str(exc))
            continue
        for id_externo in ids:
            vistas.setdefault(id_externo, None)
    return list(vistas)[:limit]


def _run_resumen_pregen_phase(limit: int = _RESUMEN_PREGEN_BATCH_SIZE) -> dict[str, Any]:
    """Calienta el caché del resumen IA para las licitaciones que se van a abrir.

    Fase opcional (``RESUMEN_PREGEN_ENABLED``, mismo patrón que la de fichas) y
    la última del job: va después de fichas y embeddings porque los dos entran
    en el contexto del resumen, y un resumen generado antes quedaría invalidado
    —su firma de estado cambia— por el trabajo de esta misma corrida.

    Solo tiene sentido con caché compartida (Redis): con la de memoria el
    resumen moriría con el proceso del job, y la fase se salta entera en vez de
    pagar por nada. El presupuesto LLM se comprueba **antes de cada**
    licitación con el BudgetGuard global: agotarlo corta el lote, porque un
    usuario que pide su resumen mañana tiene prioridad sobre calentar uno que
    quizá nadie abra. Una credencial rechazada también lo corta, por lo mismo
    que en la fase de fichas.
    """
    from config import settings

    # Any: contadores enteros más la causa textual del corte.
    counts: dict[str, Any] = {
        "generados": 0,
        "vigentes": 0,
        "vacios": 0,
        "no_encontradas": 0,
        "error": 0,
        "disabled": 0,
    }
    if not settings.RESUMEN_PREGEN_ENABLED:
        counts["disabled"] = 1
        return counts

    from services.rag.resumen import RESUMEN_CACHE_NAMESPACE, pregenerar_resumen
    from shared.cache import es_compartida, get_cache

    if not es_compartida(get_cache(RESUMEN_CACHE_NAMESPACE)):
        counts["sin_cache_compartida"] = 1
        log.warning("resumen_pregen_skipped_sin_cache_compartida")
        return counts

    from llm.budget import LLMBudgetExceeded, get_budget_guard
    from llm.providers import LLMAuthError

    guard = get_budget_guard()
    candidatas = _candidatas_resumen(limit)
    counts["candidatas"] = len(candidatas)
    for id_externo in candidatas:
        try:
            guard.check()
        except LLMBudgetExceeded as exc:
            counts["presupuesto_agotado"] = str(exc)
            log.warning("resumen_pregen_budget_exhausted", pendientes=len(candidatas))
            break
        try:
            resultado = pregenerar_resumen(id_externo, model=settings.RESUMEN_PREGEN_MODEL)
        except LLMAuthError as exc:
            counts["error"] += 1
            counts["credencial_rechazada"] = str(exc)
            log.error("resumen_pregen_auth_rejected", id_externo=id_externo, error=str(exc))
            break
        except Exception as exc:
            counts["error"] += 1
            log.warning("resumen_pregen_failed", id_externo=id_externo, error=str(exc))
            continue
        clave = {
            "generado": "generados",
            "vigente": "vigentes",
            "vacio": "vacios",
            "no_encontrada": "no_encontradas",
        }[resultado]
        counts[clave] += 1
    return counts


def run() -> dict[str, Any]:
    """Entry point del job.

    Los límites por fase vienen de ``config.settings`` (PLIEGO_FETCH_BATCH /
    PLIEGO_EMBED_BATCH / PLIEGO_FACTS_BATCH / PLIEGO_TECH_SIGNAL_BATCH /
    RESUMEN_PREGEN_BATCH); las
    constantes de módulo ``_FETCH_BATCH_SIZE`` etc. quedan como default de
    cada función para quien las invoque directamente (tests, backfills
    manuales) sin pasar por aquí.
    """
    from config import settings

    fetch_result = _run_fetch_phase(limit=settings.PLIEGO_FETCH_BATCH)
    embed_result = _run_embed_phase(limit=settings.PLIEGO_EMBED_BATCH)
    facts_result = _run_facts_phase(limit=settings.PLIEGO_FACTS_BATCH)
    tech_signal_result = _run_tech_signal_phase(limit=settings.PLIEGO_TECH_SIGNAL_BATCH)
    resumen_result = _run_resumen_pregen_phase(limit=settings.RESUMEN_PREGEN_BATCH)
    log.info(
        "documentos_embeddings_job_done",
        fetch=fetch_result,
        embed=embed_result,
        facts=facts_result,
        tech_signal=tech_signal_result,
        resumen_pregen=resumen_result,
    )
    return {
        "fetch": fetch_result,
        "embed": embed_result,
        "facts": facts_result,
        "tech_signal": tech_signal_result,
        "resumen_pregen": resumen_result,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────
#
# Invocado por .github/workflows/pliegos.yml. La lógica vive aquí y no en un
# heredoc del YAML para que pase por ruff/mypy/tests como el resto del código.


def _alertar_fichas_fallidas(facts: Mapping[str, object]) -> None:
    """Log de error y alerta que nombra la causa del fallo de la fase de fichas."""
    from observability.alerts import notify

    causa = facts.get("credencial_rechazada")
    if causa:
        cuerpo = f"{causa}. El lote de fichas se cortó en el primer rechazo."
    else:
        cuerpo = (
            f"Las {facts.get('error')} extracciones del lote fallaron sin dejar "
            "ninguna ficha; el motivo de cada una está en `documentos_facts_failed` "
            "en el log del run."
        )
    log.error("documentos_embeddings_cli_facts_failed", facts=dict(facts))
    notify(
        "error",
        "Pliegos: fallo sistémico en la fase de fichas",
        cuerpo,
        procesadas=facts.get("procesadas"),
        error=facts.get("error"),
    )


def run_cli() -> int:
    """Corre el job y falla si el lote entero de fetch o de fichas se cayó.

    Un PDF corrupto suelto es normal y esperado; que **todos** los documentos
    del lote fallen sin ninguno extraído señala un problema sistémico
    (SSRF/red/breaker abierto) que sí debe romper el workflow.

    ``unsupported`` cuenta como lote procesado (S8.2): un lote entero de
    formatos que no sabemos leer es cobertura que falta —visible en el desglose
    por formato del informe— y no un fallo de la tubería, así que no puede dejar
    el workflow en rojo todas las noches.

    La fase de fichas se juzga con ``facts_failed_systemically``. Hasta el
    2026-09-10 no se miraba: once noches seguidas con todas las llamadas al LLM
    en 401 salieron en verde, porque cada fallo se contaba como error suelto.
    Además del rojo se manda una alerta, que es la que dice la causa: el correo
    de GitHub solo dice que el run falló.

    Las dos comprobaciones se evalúan siempre, aunque la primera ya falle: una
    noche con el fetch y las fichas rotos tiene que avisar de las dos cosas.
    """
    from db.database import init_db

    init_db()
    resumen = run()
    fallo = False

    fetch = resumen["fetch"]
    if fetch.get("error") and not (fetch.get("extracted") or fetch.get("unsupported")):
        log.error("documentos_embeddings_cli_batch_failed", fetch=fetch)
        fallo = True

    facts = resumen["facts"]
    if facts_failed_systemically(facts):
        _alertar_fichas_fallidas(facts)
        fallo = True

    return 1 if fallo else 0


def report_cli() -> int:
    """Informa del estado de ``documentos``/``documento_chunks``.

    Desde S8 el informe incluye el desglose por formato (``formato_counts``) y
    la ocupación del almacén de binarios: `pliegos.yml` los pide en su resumen
    y son las dos cifras que dicen si la cobertura de formatos y el almacén
    están haciendo su trabajo, sin abrir la consola.

    Incluye además el reparto de chunks por versión de embedding (C5.7):
    durante una migración de modelo es la única forma de saber cuánto queda, y
    sin ella el re-embedding sería un job sin progreso observable.
    """
    from config.settings import settings
    from db.repositories.documentos import DocumentosRepository
    from shared.object_store import store_stats

    repo = DocumentosRepository()
    counts = repo.status_counts()
    log.info("documentos_estado", **counts)

    for fila in repo.formato_counts():
        log.info(
            "documentos_por_formato",
            content_type=fila.get("content_type") or "desconocido",
            total=fila.get("total"),
            extracted=fila.get("extracted"),
            unsupported=fila.get("unsupported"),
            error=fila.get("error"),
            pendientes=fila.get("pendientes"),
        )

    stats = store_stats()
    if stats is None:
        log.info("documentos_blob_store_no_medido")
    else:
        log.info("documentos_blob_store", objetos=stats.objetos, bytes=stats.bytes)

    try:
        por_version = repo.chunks_por_version()
    except Exception:
        # El reparto por versión es informativo: si la columna no está todavía
        # (v120 sin aplicar), el informe de estado no debe caerse por ello.
        log.warning("documentos_chunks_por_version_failed", exc_info=True)
        return 0
    pendientes = sum(int(f["n"]) for f in por_version if f["version"] != settings.EMBEDDING_VERSION)
    log.info(
        "documentos_chunks_por_version",
        vigente=settings.EMBEDDING_VERSION,
        pendientes=pendientes,
        reparto={str(f["version"]): int(f["n"]) for f in por_version},
    )
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
