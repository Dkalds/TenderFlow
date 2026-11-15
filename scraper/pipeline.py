"""Clasificación compartida del camino connector y métricas de run.

Los carriles de producción no ingieren desde aquí: ``scheduler/pipeline_runs.py``
enruta por ``PlacspAtomConnector`` / ``PlacspBulkConnector`` +
``run_connector`` (``scraper/connectors/``). Este módulo NO debe recibir
features nuevas de ingesta.

**Qué vive aquí y por qué**:

- ``_ml_classify_entry`` / ``_load_classifiers`` / ``_apply_tech_prediction``
  y las constantes ``INCLUSION_*``: el fallback ML compartido, que consume
  ``scraper.connectors.placsp._PlacspParseCore``. Es código **vivo del camino
  connector**, no legacy; vive en este fichero por historia, no por diseño.
- ``_summarize``: métricas de run que reutiliza el bucle bulk de
  ``scheduler/pipeline_runs.py``.

**Qué se retiró en 2026-11** — ``process_daily``, el carril diario legacy.
Desde el 2026-09-28 solo lo alcanzaba el replay de la DLQ para la etiqueta
``place_live_atom``, que solo escribía él mismo: no quedaba ninguna fila en
``failed_extractions`` con esa etiqueta. ``scheduler/dlq_retry.py`` la enruta
ahora por ``PlacspAtomConnector``, como ``placsp``.

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
from typing import TYPE_CHECKING, Any

from config import CPV_PREFIXES_TI, CPV_PREFIXES_UNIVERSO
from db.database import Licitacion
from observability import get_logger
from scraper.codice_parser import NS, parse_entry_unfiltered

if TYPE_CHECKING:
    # Solo para anotar. El import real sigue dentro de ``_load_classifiers``:
    # perezoso, detrás de ``ML_TECH_ENABLED`` y en el ``try`` que hace fail-open
    # la carga del modelo.
    from services.ml.tech_classifier import TechnologyClassifier

log = get_logger(__name__)

# ── ML fallback para entries sin keywords ─────────────────────────────────
# Las entradas del universo CPV (`config.CPV_PREFIXES_UNIVERSO`: 48/72/32) que
# no tienen keywords de tecnología se guardan como `cpv_ti_universe`; las TI
# (48/72) pasan además por el modelo para decidir si se rescatan o se marcan
# para revisión manual.

#: Población del clasificador: con lo que se entrenó. La 32 (telecomunicaciones,
#: 2026-10-30) entra en el universo pero no se puntúa: el modelo no la ha visto.
_TI_PREFIXES = tuple(CPV_PREFIXES_TI)
_UNIVERSO_PREFIXES = tuple(CPV_PREFIXES_UNIVERSO)

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
#: La puerta la descartó, pero un aviso TED sin pareja enlaza el expediente
#: (``scraper.connectors.placsp.EsperadasPorTed``): TED ya lo dio por tecnología.
INCLUSION_REFERENCIA_TED = "referencia_ted"


@dataclasses.dataclass(frozen=True)
class _ClassifierHolder:
    """Contenedor inmutable de los clasificadores ML cargados para este proceso.

    Reemplaza los 4 módule-level globals mutables (_ml_clf, _ml_clf_attempted,
    _tech_clf, _tech_clf_attempted) por un dataclass thread-safe cargado una
    sola vez via ``functools.lru_cache``. El cache puede limpiarse en tests
    llamando a ``_load_classifiers.cache_clear()``.
    """

    ml: Any  # SAPClassifier | None
    tech: TechnologyClassifier | None


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
    # Por `resolve_artifact`, como el `precompute` de `ml_proba`: la versión
    # activa cotejada por sha256 y, sin versión activa, el asset de nombre fijo.
    # Hasta 2026-10 era `ensure_downloaded()` + `load()`: bajaba el
    # `sap_classifier.pkl` de nombre fijo y `load()` lo servía cuando el `path`
    # de la versión activa no estaba en este runner — con nombres por
    # contenido, siempre —, así que la ingesta puntuaba con otro modelo que el
    # registrado sin que nada lo dijera.
    ml: Any = None
    try:
        from services.ml.sap_classifier import SAPClassifier

        artefacto = SAPClassifier.resolve_artifact()
        if artefacto is not None:
            ml = SAPClassifier.load(artefacto)
            log.info("pipeline.ml_clf_loaded", threshold=ml._threshold, path=str(artefacto))
    except Exception as exc:
        # La ingesta no se para por el clasificador: sin él, las entradas TI
        # sin keyword se guardan como `cpv_ti_universe`. Pero un artefacto que
        # no cuadra con el registro (`ModelArtifactMismatch`) no es «no hay
        # modelo» y no puede quedarse en un debug.
        from services.ml.model_artifacts import ModelArtifactMismatch

        if isinstance(exc, ModelArtifactMismatch):
            log.error("pipeline.ml_clf_artifact_mismatch", error=str(exc))
        else:
            log.debug("pipeline.ml_clf_unavailable", error=str(exc))

    # ── Multi-tecnología (solo si ML_TECH_ENABLED) ─────────────────────────
    tech: TechnologyClassifier | None = None
    if getattr(_settings, "ML_TECH_ENABLED", False):
        try:
            from services.ml.tech_classifier import TechnologyClassifier

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


def _get_tech_clf() -> TechnologyClassifier | None:
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
    return pred


def _ml_classify_entry(entry_elem: Any) -> Licitacion | None:
    """Entradas del universo CPV (48/72/32) sin keywords: parse + score ML.

    Devuelve la ``Licitacion`` con ``inclusion_reason`` ya decidido, o ``None``
    sólo si la entry no es TI o no se puede parsear:

      1. Comprobación rápida de CPV — descarta lo de fuera del universo sin
         parsear.
      2. Parse completo con parse_entry_unfiltered.
      3. Score con SAPClassifier (si hay modelo):
           - ml_proba < ML_UNCERTAINTY_LO   → se conserva como ``cpv_ti_universe``
                                              (sin ``tecnologia``: negativo del
                                              clasificador, pero expediente TI)
           - [ML_UNCERTAINTY_LO, threshold) → ``ml_cpv_rescue`` para revisión manual
           - [threshold, 1]                 → ``ml_cpv_rescue`` positivo confiable
         Sin modelo, si el score falla o si el CPV no es 48/72 (la 32 queda
         fuera de la población del modelo), la entry se conserva como
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
    if not cpv or not cpv.startswith(_UNIVERSO_PREFIXES):
        return None

    # 2 — Parse completo sin filtro de keywords
    lic = parse_entry_unfiltered(entry_elem)
    if lic is None:
        return None
    lic.inclusion_reason = INCLUSION_CPV_TI

    # 3 — Score ML con texto aumentado (si hay modelo y el CPV es de su población)
    if not cpv.startswith(_TI_PREFIXES):
        return lic
    clf = _get_ml_clf()
    if clf is None:
        return lic
    try:
        from services.ml.classifier_pipeline import _augment_text

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
