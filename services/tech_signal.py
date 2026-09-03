"""Señal de tecnología detectada en el texto de los pliegos, y su fusión
hacia ``licitaciones.ml_*``/``licitacion_tecnologia_score``.

Plan "categorización alimentada por los pliegos" (2026-08-04): hoy la
categorización de tecnología corre una sola vez en el ingest y solo ve
título+descripción. Esta señal añade el texto de los pliegos como fuente
separada y trazable, fusionada sin machacar la señal de título.

``score_documents`` es puro (sin I/O); ``merge_doc_signals`` orquesta lectura
y escritura a través de ``db/repositories/tecnologia_pliego.py`` (TID251: sin
SQL directo aquí).
"""

from __future__ import annotations

import json
import re
from typing import Any

from config import TECHNOLOGY_KEYWORDS
from db.database import now_utc_iso
from db.events import append_event
from db.repositories.tecnologia_pliego import TechSignal, TecnologiaPliegoRepository
from observability.logging import get_logger
from observability.runtime_metrics import pliego_tech_merge_total
from shared.tender_facts import TenderFactSheetRecord

log = get_logger(__name__)

# Mismo criterio word-boundary que scraper/filters.py (evita falsos positivos
# tipo 'sap' dentro de 'desaparecer'); reconstruido aquí en vez de importar el
# `_TECH_PATTERNS` privado de filters.py -- ambos derivan del mismo
# TECHNOLOGY_KEYWORDS, así que no hay riesgo de divergencia de contenido.
_TECH_PATTERNS: dict[str, re.Pattern[str]] = {
    tech: re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
        flags=re.IGNORECASE,
    )
    for tech, keywords in TECHNOLOGY_KEYWORDS.items()
}

# Un pliego técnico que menciona una tecnología es señal más fuerte que una
# mención de pasada en el legal (plantillas administrativas repiten términos
# genéricos). "additional" es intermedio (anexos técnicos variopintos).
_DOC_TYPE_WEIGHT: dict[str, float] = {"technical": 1.0, "additional": 0.6, "legal": 0.3}
_DEFAULT_DOC_WEIGHT = _DOC_TYPE_WEIGHT["legal"]

# Menciones ponderadas mínimas para no ser una mención incidental ("se
# ofimatiza con Office" no es señal de proyecto SAP). Y el punto donde el
# score satura a 1.0 -- no es una probabilidad calibrada, es un proxy
# monótono en señal (mismo espíritu que ``_keyword_fallback_score``).
_MIN_WEIGHTED_HITS = 2.0
_SCORE_SATURATION = 6.0


def score_documents(pages: list[dict[str, Any]]) -> dict[str, TechSignal]:
    """Puntúa cada tecnología por menciones ponderadas por tipo de documento.

    ``pages`` es la salida de ``DocumentosRepository.list_pages_by_licitacion``
    -- cada fila ya trae ``tipo`` (join contra ``documentos``), así que no
    hace falta un mapa aparte documento→tipo. Devuelve solo las tecnologías
    que superan ``_MIN_WEIGHTED_HITS``.
    """
    weighted_hits: dict[str, float] = dict.fromkeys(_TECH_PATTERNS, 0.0)
    matched: dict[str, set[str]] = {tech: set() for tech in _TECH_PATTERNS}

    for page in pages:
        text = str(page.get("texto") or "")
        if not text:
            continue
        weight = _DOC_TYPE_WEIGHT.get(str(page.get("tipo") or ""), _DEFAULT_DOC_WEIGHT)
        for tech, pattern in _TECH_PATTERNS.items():
            hits = pattern.findall(text)
            if not hits:
                continue
            weighted_hits[tech] += weight * len(hits)
            matched[tech].update(h.lower() for h in hits)

    results: dict[str, TechSignal] = {}
    for tech, weighted in weighted_hits.items():
        if weighted < _MIN_WEIGHTED_HITS:
            continue
        score = round(min(1.0, weighted / _SCORE_SATURATION), 4)
        results[tech] = TechSignal(score=score, matched_terms=sorted(matched[tech]))
    return results


def _decode_evidence(row: dict[str, Any]) -> Any:
    """Evidencia legible para el payload del evento -- decodifica el JSON
    persistido (matched_terms de keywords o evidence_json de LLM) en vez de
    reencapsular el string crudo dentro de otro JSON."""
    raw = row.get("matched_terms") or row.get("evidence_json")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _build_merge_result(
    state: dict[str, Any], pliego_scores: dict[str, float], threshold_aplicado: float
) -> dict[str, Any]:
    """Lógica de dominio pura del merge -- separada para poder correr dentro
    de ``TecnologiaPliegoRepository.merge_many_with_lock`` (que la invoca con el
    estado leído bajo el advisory lock, en la misma transacción que la
    escritura, evitando una carrera de lost-update entre planos de
    orquestación distintos -- ver el docstring de ``merge_many_with_lock``).

    ``ml_proba_max``/``ml_tech_principal`` se restringen a ``included`` (las
    tecnologías que quedan en ``ml_tecnologias``): igual que
    ``TechnologyClassifier`` nunca reporta un ``principal`` fuera de su
    propio conjunto ``predicted``, este merge no debe nombrar una tecnología
    como "principal" si ni el título/ML ni el pliego la dejaron en el CSV
    final -- ``licitacion_tecnologia_score`` puede tener filas con score>0
    para tecnologías que nunca cruzaron su propio threshold ML y por tanto
    nunca estuvieron "predichas".
    """
    existing_scores: dict[str, float] = state["scores"]
    existing_predicted: set[str] = state["predicted"]

    full_scores = dict(existing_scores)
    for tech, score in pliego_scores.items():
        full_scores[tech] = max(full_scores.get(tech, 0.0), score)

    included = existing_predicted | set(pliego_scores)
    # ``.get`` y no ``[]``: ``existing_predicted`` sale del CSV
    # ``licitaciones.ml_tecnologias`` y ``existing_scores`` de
    # ``licitacion_tecnologia_score`` -- dos tablas distintas, y nada garantiza
    # que la primera esté contenida en la segunda. ``precompute_ml_tecnologias``
    # no persiste fila para un label con score 0.0 (scraper/ml_training.py) y
    # ``_apply_tech_prediction`` (scraper/pipeline.py) delega la persistencia de
    # scores en el llamador. Indexar directo lanzaba un KeyError con el nombre
    # de la tecnología, que el fail-open de ``merge_doc_signals`` reducía a un
    # warning críptico (``error: "'SAP'"``) y dejaba a esas licitaciones sin
    # fusionar **para siempre**: 33 de ellas en cada pasada de producción hasta
    # 2026-09-02. Un 0.0 las mantiene en ml_tecnologias -- el merge nunca borra
    # lo ya predicho -- y no las deja salir como principal salvo que no haya
    # nada mejor.
    included_scores = {t: full_scores.get(t, 0.0) for t in included}
    ml_tecnologias = (
        ",".join(sorted(included, key=lambda t: -included_scores[t])) if included else None
    )
    ml_proba_max = max(included_scores.values()) if included_scores else None
    ml_tech_principal = (
        max(included_scores, key=lambda t: included_scores[t]) if included_scores else None
    )

    return {
        "ml_tecnologias": ml_tecnologias,
        "ml_proba_max": ml_proba_max,
        "ml_tech_principal": ml_tech_principal,
        "pliego_scores": [(tech, full_scores[tech]) for tech in pliego_scores],
        "threshold_aplicado": threshold_aplicado,
        "existing_scores": existing_scores,
        "full_scores": full_scores,
    }


def merge_doc_signals(licitacion_ids: list[str] | None = None) -> dict[str, int]:
    """Fusiona señales de pliego (``score >= PLIEGO_TECH_MIN_SCORE``) hacia
    ``ml_tecnologias``/``ml_proba_max``/``ml_tech_principal`` y hace upsert
    de las filas de ``licitacion_tecnologia_score`` que la señal tocó.

    Sin ``licitacion_ids``, cubre TODAS las licitaciones con señal vigente --
    uso nightly (``scheduler/pipeline_runs.py``, tras
    ``precompute_ml_tecnologias``, que clobberea las tres columnas resumen en
    cada re-scrape). Con una lista, cubre solo esas -- uso incremental tras
    puntuar un lote nuevo (``scheduler/jobs/documentos_embeddings.py``).

    Idempotente y fail-open por licitación: no depende de ``merged_at`` para
    decidir si fusiona (siempre recalcula), solo lo usa para no reemitir el
    evento de auditoría en re-corridas. El merge nunca borra una tecnología
    ya predicha por el modelo, solo añade lo que el pliego detectó encima.
    El read-modify-write en sí es atómico (``merge_many_with_lock``); el
    fail-open cubre la escritura del merge y, por separado, la emisión de
    eventos -- un fallo emitiendo el evento de UNA licitación no aborta el
    resto del lote ni deja sin fusionar a las demás.

    Toda la escritura va en un solo viaje por lote (``merge_many_with_lock``):
    la versión por licitación costaba 14 de los 20 minutos del step de cierre
    de la pipeline diaria. Lo único que sigue siendo por fila es
    ``append_event``, y solo para señales aún sin ``merged_at``.
    """
    from config import settings

    repo = TecnologiaPliegoRepository()
    signals = repo.list_signals_for_merge(
        min_score=settings.PLIEGO_TECH_MIN_SCORE, licitacion_ids=licitacion_ids
    )
    by_licitacion: dict[str, list[dict[str, Any]]] = {}
    for row in signals:
        by_licitacion.setdefault(str(row["licitacion_id"]), []).append(row)
    if not by_licitacion:
        return {"licitaciones_merged": 0, "events_emitted": 0, "errors": 0}

    pliego_scores_por_licitacion: dict[str, dict[str, float]] = {}
    for licitacion_id, rows in by_licitacion.items():
        pliego_scores: dict[str, float] = {}
        for row in rows:
            tech = str(row["tecnologia"])
            pliego_scores[tech] = max(pliego_scores.get(tech, 0.0), float(row["score"]))
        pliego_scores_por_licitacion[licitacion_id] = pliego_scores

    threshold = settings.PLIEGO_TECH_MIN_SCORE

    def _compute(licitacion_id: str, state: dict[str, Any]) -> dict[str, Any] | None:
        return _build_merge_result(
            state,
            pliego_scores=pliego_scores_por_licitacion[licitacion_id],
            threshold_aplicado=threshold,
        )

    outcome = repo.merge_many_with_lock(list(by_licitacion), _compute)

    # Los fallos ya los loguea el repositorio, uno a uno y con ``exc_info``:
    # repetirlos aquí solo duplicaría la línea, y sin la traza, que es lo único
    # que faltaba para diagnosticar el KeyError de las 33 licitaciones.
    pliego_tech_merge_total.labels(outcome="error").inc(len(outcome.errors))
    pliego_tech_merge_total.labels(outcome="ok").inc(len(outcome.results))

    events_emitted = 0
    # Un solo stamp para todo el lote: era una escritura por licitación, que
    # es justo lo que este rediseño vino a quitar. Lo que falle al emitir se
    # queda con merged_at NULL y se reintenta solo en la siguiente corrida.
    to_stamp: list[tuple[str, str, str]] = []
    for licitacion_id, result in outcome.results.items():
        existing_scores = result["existing_scores"]
        full_scores = result["full_scores"]
        for row in by_licitacion[licitacion_id]:
            if row.get("merged_at") is not None:
                continue
            tech = str(row["tecnologia"])
            method = str(row["method"])
            try:
                append_event(
                    "licitacion.tecnologia_pliego",
                    licitacion_id,
                    "licitacion",
                    {
                        "tecnologia": tech,
                        "method": method,
                        "score": full_scores.get(tech),
                        "antes": existing_scores.get(tech),
                        "evidencia": _decode_evidence(row),
                        "signal_version": row["signal_version"],
                    },
                    actor_id=None,
                )
            except Exception as exc:
                log.warning(
                    "tech_signal_event_emit_failed", licitacion_id=licitacion_id, error=str(exc)
                )
                continue
            events_emitted += 1
            to_stamp.append((licitacion_id, tech, method))

    if to_stamp:
        repo.stamp_merged(to_stamp, merged_at=now_utc_iso())

    return {
        "licitaciones_merged": len(outcome.results),
        "events_emitted": events_emitted,
        "errors": len(outcome.errors),
    }


def ingest_llm_technologies(record: TenderFactSheetRecord) -> int:
    """Normaliza ``record.facts.technologies`` (nombre libre extraído por el
    LLM) a ``TECH_LABELS`` reutilizando los patrones de ``scraper.filters``,
    persiste la señal ``method='llm'`` y funde el resultado hacia
    ``ml_tecnologias``.

    Un nombre que no mapea a ninguna tecnología conocida (vocabulario cerrado
    de ``TECH_LABELS``) se loguea y queda solo en la ficha -- no bloquea el
    resto ni la extracción, que ya se persistió antes de llamar aquí. La
    evidencia de cada mención ya viene validada contra la página real
    (``_validate_fact_evidence`` en ``services/rag/fact_sheet.py`` descarta
    cualquier hecho sin cita verificable antes de que este record exista).

    Devuelve el número de tecnologías (normalizadas) que se persistieron.
    """
    if record.facts is None or not record.facts.technologies:
        return 0

    from scraper.filters import matches_technology

    scores: dict[str, TechSignal] = {}
    for mention in record.facts.technologies:
        matched, by_tech = matches_technology(mention.name)
        if not matched:
            log.info(
                "tech_signal_llm_mention_unmapped",
                licitacion_id=record.licitacion_id,
                name=mention.name,
            )
            continue
        evidence = [e.model_dump(mode="json") for e in mention.evidence]
        for tech in by_tech:
            existing = scores.get(tech)
            if existing is None or mention.confidence > existing.score:
                scores[tech] = TechSignal(score=mention.confidence, evidence=evidence)

    if not scores:
        return 0

    repo = TecnologiaPliegoRepository()
    repo.upsert_signals(
        record.licitacion_id,
        method="llm",
        signal_version=record.extraction_version,
        scores=scores,
    )
    merge_doc_signals(licitacion_ids=[record.licitacion_id])
    return len(scores)
