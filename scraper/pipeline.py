"""Clasificación compartida + carril diario legacy (ATOM en vivo).

.. deprecated:: 2026-07-11 (F2, ADR-009)
   Los carriles de producción no pasan por aquí: ``scheduler/pipeline_runs.py``
   enruta por ``PlacspAtomConnector`` / ``PlacspBulkConnector`` +
   ``run_connector`` (``scraper/connectors/``). Este módulo NO debe recibir
   features nuevas de ingesta.

**Qué queda vivo aquí y por qué** (tras la retirada S2.1, 2026-09):

- ``_ml_classify_entry`` / ``_load_classifiers`` / ``_apply_tech_prediction``
  y las constantes ``INCLUSION_*``: el fallback ML compartido, que consume
  ``scraper.connectors.placsp._PlacspParseCore``. Es código **vivo del camino
  connector**, no legacy; vive en este fichero por historia, no por diseño.
- ``_summarize``: métricas de run que reutiliza el bucle bulk de
  ``scheduler/pipeline_runs.py``.
- ``process_daily`` / ``update_daily``: el carril diario legacy, todavía
  alcanzable con ``PLACSP_CONNECTOR_ENABLED=False`` y usado por el dispatch de
  la DLQ para las entradas históricas del cursor ``place_live_atom``. **Sí**
  escribe historial y linaje (``upsert_licitaciones_with_history``), que es lo
  que lo distingue del bulk legacy que se retiró.

**Qué se retiró en 2026-09 (S2.1)** — ``process_month``,
``_process_month_impl``, ``update_recent`` y ``backfill``. Eran los dos
caminos bulk/backfill, y seguían siendo escritores de producción vía
``scheduler/dlq_retry.py`` (entradas ``bulk_YYYYMM``) y
``run_backfill_pipeline``. Escribían con ``upsert_licitaciones`` —sin
historial— y sin lotes, sin metadatos de documentos, sin detección de
duplicados, sin ``source_ingestion_health`` y sin las columnas de linaje
(``inclusion_reason``, ``filter_version``, ``analysis_universe``). Su
sustituto es ``PlacspBulkConnector`` + ``run_connector`` mes a mes, que ya
existía y hace las siete cosas.
"""

from __future__ import annotations

import dataclasses
import functools
from typing import Any

from db.database import (
    Licitacion,
    UpsertResult,
    close_pool,
    get_cursor,
    init_db,
    log_extraccion,
    replace_adjudicaciones_batch,
    set_cursor,
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
from scraper.codice_parser import (
    NS,
    parse_adjudicaciones,
    parse_entry,
    parse_entry_unfiltered,
)

log = get_logger(__name__)

_DAILY_SOURCE = "place_live_atom"
# OJO: `_DAILY_SOURCE` es la etiqueta del CARRIL (nombre del cursor de ingesta,
# scope de DLQ y de métricas), no el valor de `licitaciones.fuente`. Las filas
# que escribe el carril diario se quedan con el default del modelo, `placsp`
# (db/upsert.py:175) -- en producción no existe ni una licitación con
# fuente='place_live_atom'. Acotar la resolución por la etiqueta en vez de por
# la fuente real no resolvería nada.
_DAILY_FUENTE = "placsp"


def _resolve_empresas_post_ingestion(fuente: str, *, scope_fuente: str | None) -> None:
    """Enlaza las adjudicaciones pendientes con el maestro de empresas.

    ``fuente`` es la etiqueta del carril (procedencia de los aliases, logs);
    ``scope_fuente`` es el valor de ``licitaciones.fuente`` al que se acota el
    recorrido, o ``None`` para recorrer la tabla entera. Van separados y
    explícitos a propósito: no siempre coinciden (ver ``_DAILY_FUENTE``), y
    confundirlos fue justamente el bug de 2026-08 que dejó la resolución
    barriendo el millón de filas de PSCP en cada ingesta de cualquier fuente.
    """
    try:
        from services.entity_resolution import HOOK_TIME_BUDGET_S, resolve_all_unlinked

        resolve_all_unlinked(
            fuente=fuente,
            scope_fuente=scope_fuente,
            resume=True,
            time_budget_s=HOOK_TIME_BUDGET_S,
        )
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
    """Invalida la caché del API tras una ingestión (shared.cache_signal).

    Fail-open: cualquier error se loguea como debug sin propagar. El evento
    ``faiss.index_stale`` que también se emitía aquí se retiró en 2026-08:
    FAISS salió del producto en la Fase 3 de reducción de superficie
    (2026-07-04) y ningún consumidor leía ese evento.
    """
    try:
        from shared.cache_signal import signal_cache_invalidation

        signal_cache_invalidation()
    except Exception:
        log.debug("cache_signal_failed", fuente=fuente)


# ── ML fallback para entries sin keywords ─────────────────────────────────
# Solo se aplica al carril diario (ATOM feed). Las entradas TI (CPV 48/72)
# que no tienen keywords de tecnología se pasan al modelo para decidir si
# incluirlas o marcarlas para revisión manual.

_TI_PREFIXES = ("48", "72")

# Motivos de inclusión que persiste el linaje (``licitaciones.inclusion_reason``).
# ``cpv_ti_universe`` es nuevo desde 2026-09: antes un expediente de CPV 48/72
# sin keyword que el modelo no aceptaba se **descartaba antes de guardarse**, y
# como la LCSP (art. 126) restringe nombrar marcas en los pliegos, eso dejaba
# fuera justo las implantaciones nuevas —«un ERP», «una plataforma de RRHH»—
# que son las oportunidades grandes. Ahora se conservan con este motivo, sin
# ``tecnologia`` (el listado por defecto no las enseña; las reglas, la búsqueda
# y el Investigador sí las ven), igual que TED guarda ya todo su CPV 48/72.
INCLUSION_KEYWORD = "keyword"
INCLUSION_ML_RESCUE = "ml_cpv_rescue"
INCLUSION_CPV_TI = "cpv_ti_universe"


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

            TechnologyClassifier.ensure_downloaded()
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
    """Entradas TI (CPV 48/72) sin keywords de tecnología: parse + score ML.

    Devuelve la ``Licitacion`` con ``inclusion_reason`` ya decidido, o ``None``
    sólo si la entry no es TI o no se puede parsear:

      1. Comprobación rápida de CPV — descarta no-TI sin parsear.
      2. Parse completo con parse_entry_unfiltered.
      3. Score con SAPClassifier (si hay modelo):
           - ml_proba < ML_UNCERTAINTY_LO   → se conserva como ``cpv_ti_universe``
                                              (sin ``tecnologia``: negativo del
                                              clasificador, pero expediente TI)
           - [ML_UNCERTAINTY_LO, threshold) → ``ml_cpv_rescue`` para revisión manual
           - [threshold, 1]                 → ``ml_cpv_rescue`` positivo confiable
         Sin modelo, o si el score falla, la entry se conserva como
         ``cpv_ti_universe``: la regla de CPV no depende del clasificador.
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

    # 2 — Parse completo sin filtro de keywords
    lic = parse_entry_unfiltered(entry_elem)
    if lic is None:
        return None
    lic.inclusion_reason = INCLUSION_CPV_TI

    # 3 — Score ML con texto aumentado (si hay modelo)
    clf = _get_ml_clf()
    if clf is None:
        return lic
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
        return lic

    lic.ml_proba = proba
    lic.classifier_model_version = str(getattr(clf, "metadata", {}).get("trained_at") or "unknown")

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
        # Negativo confiable del clasificador. Antes se descartaba; ahora queda
        # como expediente TI sin familia, que es lo que es.
        log.debug("pipeline.cpv_ti_kept", id=lic.id_externo, ml_proba=round(proba, 3))
        return lic

    lic.inclusion_reason = INCLUSION_ML_RESCUE
    log.info(
        "pipeline.ml_fallback_accepted",
        id=lic.id_externo,
        ml_proba=round(proba, 3),
        zone="uncertain" if proba < clf._threshold else "confident",
        accepted_by_tech=accepted_by_tech,
        ml_tech_principal=lic.ml_tech_principal,
    )
    return lic


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
            inclusion_reason = INCLUSION_KEYWORD
            if lic is None:
                lic = _ml_classify_entry(entry_elem)
                # El fallback decide el motivo (rescate ML o universo CPV).
                inclusion_reason = (
                    (lic.inclusion_reason or INCLUSION_ML_RESCUE) if lic else INCLUSION_ML_RESCUE
                )
            if lic:
                from scraper.lineage import current_filter_version

                lic.filter_version = current_filter_version()
                lic.inclusion_reason = inclusion_reason
                lic.analysis_universe = "technology_observed"
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

    # Enlace con el maestro de empresas + señal de invalidación de caché.
    # `fuente` es `place_live_atom` (etiqueta del carril); lo que este pipeline
    # graba en `licitaciones.fuente` es `placsp`. Ver `_DAILY_FUENTE`.
    _resolve_empresas_post_ingestion(fuente, scope_fuente=_DAILY_FUENTE)
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
