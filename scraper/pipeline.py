"""Pipeline completo: descarga -> parseo -> filtrado tecnología -> persistencia.

.. deprecated:: 2026-07-11 (F2, ADR-009)
   Los carriles **daily** y **bulk** de producción ya NO pasan por este módulo:
   con ``PLACSP_CONNECTOR_ENABLED=True``, ``scheduler/pipeline_runs.py`` enruta
   por ``PlacspAtomConnector`` / ``PlacspBulkConnector`` + ``run_connector``
   (``scraper/connectors/``). Este módulo se conserva como camino de rollback
   (flip a False) y NO debe recibir features nuevas de ingesta.

   Siguen vivos y en uso desde aquí (no mover hasta retirar el legacy):
   - ``_ml_classify_entry`` / ``_load_classifiers``: el fallback ML compartido,
     consumido por ``scraper.connectors.placsp._PlacspParseCore``.
   - ``backfill``: el carril de backfill histórico aún no tiene camino
     connector (``run_backfill_pipeline`` delega aquí).
   - ``_summarize``: métricas de run reutilizadas por el wrapper bulk connector.
"""

from __future__ import annotations

import dataclasses
import functools
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta

from db.database import (
    Licitacion,
    UpsertResult,
    close_pool,
    get_cursor,
    init_db,
    log_extraccion,
    replace_adjudicaciones_batch,
    set_cursor,
    upsert_licitaciones,
    upsert_licitaciones_with_history,
)
from db.dlq import record_failure
from observability import (
    AlertLevel,
    bind_run_context,
    get_logger,
    notify,
    record_run,
    traced,
)
from scraper.bulk_downloader import (
    CircuitOpenError,
    download_month,
    iter_xml_files,
)
from scraper.codice_parser import (
    NS,
    parse_adjudicaciones,
    parse_atom_bytes,
    parse_entry,
    parse_entry_unfiltered,
)

log = get_logger(__name__)

_DAILY_SOURCE = "place_live_atom"


def _resolve_empresas_post_ingestion(fuente: str) -> None:
    """Enlaza las adjudicaciones recién insertadas con el maestro de empresas.

    Un lote suele bastar para una ingesta incremental; el remanente lo
    recoge la siguiente ejecución o el backfill (idempotente). Fail-open:
    un error aquí no debe tumbar la ingesta.
    """
    try:
        from services.entity_resolution import resolve_unlinked_adjudicaciones

        resolve_unlinked_adjudicaciones(fuente=fuente)
    except Exception as e:
        log.warning("entity_resolution_post_ingestion_failed", fuente=fuente, error=str(e))
    # Eventos de contrato (v38): deriva adjudicación/modificación/prórroga
    # de las filas nuevas de licitaciones_history. Fail-open.
    try:
        from services.contract_events import derive_new_events

        derive_new_events()
    except Exception as e:
        log.warning("contract_events_post_ingestion_failed", fuente=fuente, error=str(e))


def _signal_post_ingestion(fuente: str) -> None:
    """Señaliza al dashboard y FAISS que hubo nueva ingestión de datos.

    Combina dos operaciones que se repiten en process_month y process_daily:
    1. Invalidación de caché del dashboard (shared.cache_signal).
    2. Evento de dominio ``faiss.index_stale`` para reconstrucción del índice.

    Fail-open: cualquier error se loguea como debug sin propagar.
    """
    try:
        from shared.cache_signal import signal_cache_invalidation

        signal_cache_invalidation()
    except Exception:
        log.debug("cache_signal_failed", fuente=fuente)

    try:
        from db.events import append_event

        append_event(
            "faiss.index_stale",
            "faiss_index",
            "ml_index",
            {"reason": "ingestion_completed", "fuente": fuente},
        )
    except Exception:
        log.debug("faiss_index_stale_event_failed", fuente=fuente)


# ── ML fallback para entries sin keywords ─────────────────────────────────
# Solo se aplica al carril diario (ATOM feed). Las entradas TI (CPV 48/72)
# que no tienen keywords de tecnología se pasan al modelo para decidir si
# incluirlas o marcarlas para revisión manual.

_TI_PREFIXES = ("48", "72")


@dataclasses.dataclass(frozen=True)
class _ClassifierHolder:
    """Contenedor inmutable de los clasificadores ML cargados para este proceso.

    Reemplaza los 4 módule-level globals mutables (_ml_clf, _ml_clf_attempted,
    _tech_clf, _tech_clf_attempted) por un dataclass thread-safe cargado una
    sola vez via ``functools.lru_cache``. El cache puede limpiarse en tests
    llamando a ``_load_classifiers.cache_clear()``.
    """

    ml: Any  # SAPClassifier | None
    tech: Any  # TechnologyClassifier | None


@functools.lru_cache(maxsize=1)
def _load_classifiers() -> _ClassifierHolder:
    """Carga SAPClassifier y TechnologyClassifier una sola vez por proceso.

    Thread-safe gracias a ``lru_cache``: si dos hilos invocan esta función
    simultáneamente, solo uno ejecutará el cuerpo y el otro esperará el resultado.
    Para tests: ``_load_classifiers.cache_clear()`` antes de cada test que necesite
    inyectar mocks.
    """
    from config import settings as _settings

    # ── SAP binario ────────────────────────────────────────────────────────
    ml: Any = None
    try:
        from scraper.ml_classifier import SAPClassifier

        SAPClassifier.ensure_downloaded()
        if SAPClassifier.is_available():
            ml = SAPClassifier.load()
            log.info("pipeline.ml_clf_loaded", threshold=ml._threshold)
    except Exception:
        log.debug("pipeline.ml_clf_unavailable")

    # ── Multi-tecnología (solo si ML_TECH_ENABLED) ─────────────────────────
    tech: Any = None
    if getattr(_settings, "ML_TECH_ENABLED", False):
        try:
            from scraper.tech_classifier import TechnologyClassifier

            if TechnologyClassifier.is_available():
                tech = TechnologyClassifier.load()
                log.info(
                    "pipeline.tech_clf_loaded",
                    n_models=len(tech._models),
                    practices=list(getattr(_settings, "ML_TECH_GATING_PRACTICES", [])),
                )
        except Exception as exc:
            log.debug("pipeline.tech_clf_unavailable", error=str(exc))

    return _ClassifierHolder(ml=ml, tech=tech)


def _get_ml_clf() -> Any:
    """Devuelve el SAPClassifier cargado. None si no disponible."""
    return _load_classifiers().ml


def _get_tech_clf() -> Any:
    """Devuelve el TechnologyClassifier cargado. None si deshabilitado o no disponible."""
    return _load_classifiers().tech


def _apply_tech_prediction(lic: Licitacion) -> dict[str, Any] | None:
    """Anota ``lic`` con ml_tecnologias / ml_proba_max / ml_tech_principal.

    Devuelve el dict de predicción (con ``scores`` y ``thresholds``) para que
    los llamadores puedan persistirlo en ``licitacion_tecnologia_score``.
    Si el clasificador multi-tech está deshabilitado o falla, devuelve None.
    """
    tech_clf = _get_tech_clf()
    if tech_clf is None:
        return None
    try:
        text = ((lic.titulo or "") + " " + (lic.descripcion or "")).strip()
        pred = tech_clf.predict_one(text, cpv=lic.cpv, importe=lic.importe)
    except Exception as exc:
        log.debug("pipeline.tech_predict_failed", id=lic.id_externo, error=str(exc))
        return None
    lic.ml_tecnologias = ",".join(pred["predicted"]) if pred["predicted"] else None
    lic.ml_proba_max = float(pred["max_proba"])
    lic.ml_tech_principal = pred["principal"]
    return pred  # type: ignore[no-any-return]


def _ml_classify_entry(entry_elem: Any) -> Licitacion | None:
    """Fallback ML para entries TI (CPV 48/72) sin keywords de tecnología.

    Flujo:
      1. Comprobación rápida de CPV — descarta no-TI sin parsear.
      2. Carga el clasificador (singleton por proceso).
      3. Parse completo con parse_entry_unfiltered.
      4. Score con SAPClassifier:
           - ml_proba < ML_UNCERTAINTY_LO   → None (negativo confiable, descartar)
           - [ML_UNCERTAINTY_LO, threshold) → incluir para revisión manual (active learning)
           - [threshold, 1]                 → incluir como positivo confiable
    """
    from config import settings

    # 1 — Comprobación rápida de CPV antes del parse completo
    cpv_vals = entry_elem.xpath(
        "./cacext:ContractFolderStatus/cac:ProcurementProject"
        "/cac:RequiredCommodityClassification/cbc:ItemClassificationCode/text()",
        namespaces=NS,
    )
    cpv = cpv_vals[0] if cpv_vals else None
    if not cpv or not any(cpv.startswith(p) for p in _TI_PREFIXES):
        return None

    # 2 — Verificar modelo disponible antes del parse (evitar parse inútil)
    clf = _get_ml_clf()
    if clf is None:
        return None

    # 3 — Parse completo sin filtro de keywords
    lic = parse_entry_unfiltered(entry_elem)
    if lic is None:
        return None

    # 4 — Score ML con texto aumentado
    try:
        from scraper.ml_pipeline import _augment_text

        text = _augment_text(
            ((lic.titulo or "") + " " + (lic.descripcion or "")).strip(),
            cpv=lic.cpv,
            importe=lic.importe,
        )
        proba = float(clf.pipeline.predict_proba([text])[0][1])
    except Exception as exc:
        log.debug("pipeline.ml_score_failed", error=str(exc))
        return None

    lic.ml_proba = proba

    # Anotación multi-tecnología (no-op si ML_TECH_ENABLED=False).
    tech_pred = _apply_tech_prediction(lic)

    # Gating extendido: aceptar si alguna práctica activa supera su threshold.
    accepted_by_tech: str | None = None
    if tech_pred is not None:
        practices = set(getattr(settings, "ML_TECH_GATING_PRACTICES", []) or [])
        # SAP siempre se decide por ``proba`` (P(SAP) del binario) — no por el
        # tech_clf — para preservar compatibilidad con el threshold histórico.
        for label in tech_pred.get("predicted", []):
            if label == "SAP":
                continue
            if label in practices:
                accepted_by_tech = label
                break

    if proba < settings.ML_UNCERTAINTY_LO and accepted_by_tech is None:
        return None  # negativo confiable → descartar

    log.info(
        "pipeline.ml_fallback_accepted",
        id=lic.id_externo,
        ml_proba=round(proba, 3),
        zone="uncertain" if proba < clf._threshold else "confident",
        accepted_by_tech=accepted_by_tech,
        ml_tech_principal=lic.ml_tech_principal,
    )
    return lic


@traced("scraper.process_month")
def process_month(
    year: int, month: int, *, run_id: str | None = None, force: bool = False
) -> dict[str, Any]:
    """Procesa un mes: descarga ZIP, parsea, filtra por tecnología, persiste.

    Garantiza el cierre de la conexión DB del hilo worker actual al finalizar,
    independientemente del resultado (éxito, error o circuit open).
    """
    fuente = f"bulk_{year}{month:02d}"
    try:
        return _process_month_impl(year, month, run_id=run_id, force=force, fuente=fuente)
    finally:
        close_pool()


def _process_month_impl(
    year: int, month: int, *, run_id: str | None, force: bool, fuente: str
) -> dict[str, Any]:
    """Implementación interna de process_month (sin gestión de recursos del hilo)."""
    try:
        zip_path = download_month(year, month, force=force)
    except CircuitOpenError as e:
        log.error("month_circuit_open", year=year, month=month, error=str(e))
        record_failure(run_id, fuente, e, scope="download")
        notify(
            AlertLevel.ERROR,
            "PLACSP circuit breaker abierto",
            "El scraper no pudo descargar por fallos consecutivos en PLACSP.",
            year=year,
            month=month,
        )
        return {"year": year, "month": month, "status": "circuit_open"}
    except Exception as e:
        log.exception("month_download_error", year=year, month=month)
        record_failure(run_id, fuente, e, scope="download")
        return {"year": year, "month": month, "status": "error_descarga"}

    if zip_path is None:
        return {"year": year, "month": month, "status": "no_publicado"}

    encontradas = []
    adj_por_lic: dict[str, list[Any]] = {}
    entries_error = 0
    for filename, content in iter_xml_files(zip_path):
        log.info("xml_parse_start", filename=filename)
        try:
            for lic, adjudicaciones in parse_atom_bytes(content):
                encontradas.append(lic)
                if adjudicaciones:
                    adj_por_lic[lic.id_externo] = adjudicaciones
        except Exception as e:
            log.exception("xml_parse_error", filename=filename, year=year, month=month)
            record_failure(run_id, fuente, e, scope="parse", payload_ref=filename)
            entries_error += 1

    try:
        nuevas, actualizadas = upsert_licitaciones(encontradas)
    except Exception as e:
        log.exception("month_persist_error", year=year, month=month)
        record_failure(run_id, fuente, e, scope="persist_licitaciones")
        return {"year": year, "month": month, "status": "error_persistencia"}

    n_adj = 0
    n_adj_dropped = 0
    n_adj_failed = 0
    if adj_por_lic:
        try:
            n_adj, n_adj_dropped, n_adj_failed = replace_adjudicaciones_batch(
                adj_por_lic, run_id=run_id, fuente=fuente
            )
            if n_adj_dropped:
                log.warning("adj_rows_dropped", dropped=n_adj_dropped, persisted=n_adj)
        except Exception as e:
            log.warning("month_adj_persist_error", error=str(e))
            record_failure(run_id, fuente, e, scope="persist_adjudicaciones")

    log_extraccion(
        fuente=fuente,
        nuevas=nuevas,
        actualizadas=actualizadas,
        total=len(encontradas),
        notas=f"matches:{len(encontradas)} adj:{n_adj} adj_errors:{n_adj_failed} errors:{entries_error}",
    )

    # Instrumentación Prometheus (no bloquea si falla)
    try:
        from observability.prometheus import RunInstrumentation, _write_metrics

        prom = RunInstrumentation(source=fuente)
        prom.record_items(nuevas=nuevas, actualizadas=actualizadas)
        prom.record_parse_error(entries_error)
        _write_metrics(prom)
    except Exception:
        log.debug("prometheus_instrumentation_failed", fuente=fuente)

    # Enlace con el maestro de empresas + señal de invalidación de caché
    _resolve_empresas_post_ingestion(fuente)
    _signal_post_ingestion(fuente)

    return {
        "year": year,
        "month": month,
        "status": "ok",
        "tech_matches": len(encontradas),
        "adjudicaciones": n_adj,
        "adj_errors": n_adj_failed,
        "nuevas": nuevas,
        "actualizadas": actualizadas,
        "entries_error": entries_error,
    }


def _summarize(results: list[dict[str, Any]], metrics: Any) -> None:
    adj_errors_total = 0
    for r in results:
        metrics.months_attempted += 1
        if r["status"] == "ok":
            metrics.months_ok += 1
            metrics.licitaciones_nuevas += r.get("nuevas", 0)
            metrics.licitaciones_actualizadas += r.get("actualizadas", 0)
            metrics.adjudicaciones += r.get("adjudicaciones", 0)
            metrics.errores_parseo += r.get("entries_error", 0)
            adj_errors_total += r.get("adj_errors", 0)
        elif r["status"] == "no_publicado":
            metrics.months_ok += 1
        else:
            metrics.months_failed += 1
            if r["status"] == "error_descarga":
                metrics.errores_descarga += 1
    if adj_errors_total:
        metrics.notas = f"adj_persist_errors:{adj_errors_total}"


def update_recent(months_back: int = 3) -> list[dict[str, Any]]:
    """Actualiza los últimos N meses (idempotente gracias al upsert)."""
    init_db()
    today = datetime.now(UTC).date()
    run_id = bind_run_context(entrypoint="update_recent", months_back=months_back)
    with record_run(run_id) as metrics:
        results = []
        for i in range(months_back):
            target = today - relativedelta(months=i)
            results.append(process_month(target.year, target.month, run_id=run_id))
        _summarize(results, metrics)
    return results


def backfill(start_year: int, start_month: int) -> list[dict[str, Any]]:
    """Backfill desde una fecha histórica hasta hoy (paralelo por meses)."""
    if not (1 <= start_month <= 12):
        raise ValueError(f"start_month must be 1-12, got {start_month}")
    if start_year < 2000:
        raise ValueError(f"start_year must be >= 2000, got {start_year}")
    from config import settings

    init_db()
    today = datetime.now(UTC).date()
    cur = date(start_year, start_month, 1)
    run_id = bind_run_context(entrypoint="backfill", start_year=start_year, start_month=start_month)

    months: list[tuple[int, int]] = []
    while cur <= today:
        months.append((cur.year, cur.month))
        cur += relativedelta(months=1)

    workers = min(settings.BACKFILL_MAX_WORKERS, len(months)) or 1
    log.info("backfill_start", months=len(months), workers=workers)

    with record_run(run_id) as metrics:
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(process_month, y, m, run_id=run_id): (y, m) for y, m in months}
            for future in as_completed(futures):
                y, m = futures[future]
                try:
                    results.append(future.result())
                except Exception:
                    log.exception("backfill_month_error", year=y, month=m)
                    results.append({"year": y, "month": m, "status": "error"})
            # Nota: las conexiones DB de cada worker se cierran en process_month via finally.
        _summarize(results, metrics)
    return results


# ---------------------------------------------------------------------------
# Carril diario — feed ATOM en vivo
# ---------------------------------------------------------------------------


def process_daily(*, run_id: str | None = None) -> dict[str, Any]:
    """Procesa el feed ATOM en vivo: pagina, filtra por tecnología, persiste con historial.

    Returns:
        dict con status, contadores y listas de ids insertados/modificados.
    """
    from scraper.atom_live import iter_live_entries

    init_db()
    fuente = _DAILY_SOURCE

    # Leer cursor actual
    cursor = get_cursor(fuente)
    last_seen_updated = cursor["last_seen_updated"] if cursor else None

    try:
        entries, meta = iter_live_entries(last_seen_updated=last_seen_updated)
    except Exception as e:
        log.exception("daily_fetch_error")
        record_failure(run_id, fuente, e, scope="fetch")
        notify(
            AlertLevel.ERROR,
            "Feed diario ATOM falló al descargar",
            body=str(e),
        )
        return {"status": "error_fetch", "source": fuente}

    if not entries:
        log.info("daily_no_new_entries", stopped=meta.get("stopped_reason"))
        # Actualizar cursor etag/last_modified incluso sin entries
        if meta.get("etag") or meta.get("last_modified"):
            set_cursor(
                fuente,
                last_seen_updated=last_seen_updated,
                etag=meta.get("etag"),
                last_modified=meta.get("last_modified"),
            )
        return {
            "status": "ok",
            "source": fuente,
            "tech_matches": 0,
            "inserted": [],
            "modified": [],
            "unchanged": [],
            "pages_fetched": meta["pages_fetched"],
            "entries_seen": meta["entries_seen"],
        }

    # Parsear entries y filtrar por tecnología
    encontradas = []
    adj_por_lic: dict[str, list[Any]] = {}
    entries_error = 0

    for entry_elem, updated_str in entries:
        try:
            lic = parse_entry(entry_elem)
            if lic is None:
                lic = _ml_classify_entry(entry_elem)
            if lic:
                # Actualizar fecha_actualizacion_fuente con el <updated> de la entry
                if updated_str:
                    lic.fecha_actualizacion_fuente = updated_str
                encontradas.append(lic)
                adj = parse_adjudicaciones(entry_elem, lic.id_externo)
                if adj:
                    adj_por_lic[lic.id_externo] = adj
        except Exception as e:
            log.warning("daily_entry_parse_error", error=str(e))
            record_failure(run_id, fuente, e, scope="parse")
            entries_error += 1

    # Persistir con detección de cambios
    try:
        from config import settings as _cfg

        upsert_result: UpsertResult = upsert_licitaciones_with_history(
            encontradas,
            source=fuente,
            chunk_size=_cfg.UPSERT_CHUNK_SIZE,
        )
    except Exception as e:
        log.exception("daily_persist_error")
        record_failure(run_id, fuente, e, scope="persist_licitaciones")
        return {"status": "error_persistencia", "source": fuente}

    # Adjudicaciones
    n_adj = 0
    if adj_por_lic:
        n_adj, n_adj_dropped, _adj_failed = replace_adjudicaciones_batch(
            adj_por_lic, run_id=run_id, fuente=fuente
        )
        if n_adj_dropped:
            log.warning("adj_rows_dropped", dropped=n_adj_dropped, persisted=n_adj)

    # Actualizar cursor
    newest = meta.get("newest_updated") or last_seen_updated
    set_cursor(
        fuente,
        last_seen_updated=newest,
        etag=meta.get("etag"),
        last_modified=meta.get("last_modified"),
    )

    # Log de extracción
    log_extraccion(
        fuente=fuente,
        nuevas=upsert_result.nuevas,
        actualizadas=upsert_result.actualizadas,
        total=len(encontradas),
        notas=(
            f"matches:{len(encontradas)} adj:{n_adj} "
            f"inserted:{upsert_result.nuevas} modified:{len(upsert_result.modified)} "
            f"unchanged:{len(upsert_result.unchanged)} errors:{entries_error} "
            f"pages:{meta['pages_fetched']}"
        ),
    )

    log.info(
        "daily_pipeline_done",
        tech_matches=len(encontradas),
        inserted=upsert_result.nuevas,
        modified=len(upsert_result.modified),
        unchanged=len(upsert_result.unchanged),
        adjudicaciones=n_adj,
        pages=meta["pages_fetched"],
        entries_seen=meta["entries_seen"],
    )

    # Enlace con el maestro de empresas + señal de invalidación de caché
    _resolve_empresas_post_ingestion(fuente)
    _signal_post_ingestion(fuente)

    return {
        "status": "ok",
        "source": fuente,
        "tech_matches": len(encontradas),
        "adjudicaciones": n_adj,
        "inserted": upsert_result.inserted,
        "modified": upsert_result.modified,
        "unchanged": upsert_result.unchanged,
        "entries_error": entries_error,
        "pages_fetched": meta["pages_fetched"],
        "entries_seen": meta["entries_seen"],
    }


@traced("scraper.update_daily")
def update_daily() -> dict[str, Any]:
    """Punto de entrada para el carril diario con observabilidad.

    Garantiza el cierre de la conexión DB del hilo worker actual al finalizar,
    independientemente del resultado (éxito o error).
    """
    init_db()
    run_id = bind_run_context(entrypoint="update_daily")
    try:
        with record_run(run_id) as metrics:
            result = process_daily(run_id=run_id)
            if result["status"] == "ok":
                metrics.status = "ok"
                metrics.licitaciones_nuevas = len(result.get("inserted", []))
                metrics.licitaciones_actualizadas = len(result.get("modified", []))
            else:
                metrics.status = "error"
                metrics.months_failed = 1
            metrics.notas = f"daily|{result['status']}"
        return result
    finally:
        close_pool()
