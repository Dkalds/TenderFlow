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
import unicodedata
from collections.abc import Iterable
from typing import Any

from config.keywords import (
    KEYWORDS_DE_TRAMITACION,
    TECH_LABEL_TIPO,
    es_ambigua,
    patron_de_keyword,
    plegar,
)
from db.database import now_utc_iso
from db.events import append_event
from db.repositories.tecnologia_pliego import TechSignal, TecnologiaPliegoRepository
from observability.logging import get_logger
from observability.runtime_metrics import pliego_tech_merge_total
from shared.tender_facts import TenderFactSheetRecord

log = get_logger(__name__)


def _tech_patterns() -> dict[str, re.Pattern[str]]:
    """Patrones del diccionario vigente, compartidos con `scraper/filters.py`.

    Antes cada módulo compilaba los suyos desde `TECHNOLOGY_KEYWORDS` con el
    argumento de que «ambos derivan de lo mismo, así que no divergen». Con el
    diccionario en base de datos (C5.6) eso deja de ser cierto: dos procesos
    podrían tener versiones distintas cacheadas. Ahora los dos piden a
    `services.tecnologias_diccionario`, que memoiza por versión — así que
    comparten contenido *y* momento.
    """
    from services.tecnologias_diccionario import patrones

    return patrones()


def _tech_keywords() -> dict[str, list[str]]:
    """Keywords del diccionario vigente, para contar por término canónico."""
    from services.tecnologias_diccionario import vigente

    return vigente()[0]


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

# Precisión de la señal (2026-10-30). Las etiquetas sobraban porque un pliego
# de cien páginas repite su plantilla: el legal nombra el «Esquema Nacional de
# Seguridad» diez veces en cualquier contrato con datos, y a peso 0,3 eso ya
# fusionaba CIBERSEGURIDAD. Cuatro reglas, todas por tecnología:
#
# 1. Lo que solo aparece en el legal (o en un documento sin tipo) no etiqueta.
# 2. Un término cuenta como mucho ``_TOPE_POR_TERMINO`` menciones ponderadas:
#    la misma frase repetida no es más evidencia que dicha tres veces.
# 3. Si todos los términos son ambiguos no etiqueta: aquí no hay CPV que los
#    corrobore. Ambiguo en un pliego es ``config.keywords.KEYWORDS_AMBIGUAS``
#    más ``KEYWORDS_DE_TRAMITACION`` («firma electrónica», «licitación
#    electrónica», «esquema nacional de seguridad»…, que cualquier pliego dice;
#    medido en producción el 2026-10-30).
# 4. Una categoría (ERP, CLOUD_INFRA…) necesita ``_MIN_TERMINOS_CATEGORIA``
#    términos firmes distintos; un fabricante, uno: «SAP S/4HANA» no es
#    vocabulario genérico, «copias de seguridad» sí. Las ambiguas suman
#    menciones pero no cuentan como término.
_TIPOS_QUE_ETIQUETAN = frozenset({"technical", "additional"})
_TOPE_POR_TERMINO = 3.0
_MIN_TERMINOS_CATEGORIA = 2


def _ambigua_en_pliego(termino: str) -> bool:
    return es_ambigua(termino) or termino.casefold() in KEYWORDS_DE_TRAMITACION


def score_documents(pages: list[dict[str, Any]]) -> dict[str, TechSignal]:
    """Puntúa cada tecnología por menciones ponderadas por tipo de documento.

    ``pages`` es la salida de ``DocumentosRepository.list_pages_by_licitacion``
    -- cada fila ya trae ``tipo`` (join contra ``documentos``), así que no
    hace falta un mapa aparte documento→tipo. Devuelve solo las tecnologías
    que pasan las reglas de precisión de arriba y superan ``_MIN_WEIGHTED_HITS``.
    ``matched_terms`` son las keywords en su forma canónica del diccionario.
    """
    # Una sola lectura del diccionario para toda la pasada: pedirlo por página
    # tomaba el lock cada vez y, si su versión cambiaba a mitad del bucle, una
    # tecnología nueva hacía saltar `KeyError`. Los patrones solo descartan
    # rápido las tecnologías que no aparecen; si su versión no coincidiera con
    # la del diccionario, una tecnología sin keywords simplemente no puntúa.
    patrones = _tech_patterns()
    diccionario = _tech_keywords()
    por_termino: dict[str, dict[str, float]] = {tech: {} for tech in patrones}
    fuera_del_legal: set[str] = set()
    canonicas: dict[tuple[str, str], str] = {}

    for page in pages:
        # NFC: el texto extraído de un PDF llega a menudo con la tilde como
        # signo aparte, y el patrón compila las letras precompuestas.
        text = unicodedata.normalize("NFC", str(page.get("texto") or ""))
        if not text:
            continue
        tipo = str(page.get("tipo") or "")
        weight = _DOC_TYPE_WEIGHT.get(tipo, _DEFAULT_DOC_WEIGHT)
        for tech, pattern in patrones.items():
            # `finditer` sobre la alternancia (de la keyword más larga a la más
            # corta) da una mención por posición: «SAP HANA» es `sap hana` y
            # no además `sap` y `hana`, que contarían como tres términos.
            for match in pattern.finditer(text):
                casado = match.group().lower()
                clave = (tech, casado)
                if clave not in canonicas:
                    canonicas[clave] = _forma_canonica(casado, diccionario.get(tech, ()))
                terminos = por_termino[tech]
                canonica = canonicas[clave]
                terminos[canonica] = terminos.get(canonica, 0.0) + weight
                if tipo in _TIPOS_QUE_ETIQUETAN:
                    fuera_del_legal.add(tech)

    results: dict[str, TechSignal] = {}
    for tech, terminos in por_termino.items():
        if not terminos or tech not in fuera_del_legal:
            continue
        if all(_ambigua_en_pliego(t) for t in terminos):
            continue
        if (
            TECH_LABEL_TIPO.get(tech) == "categoria"
            and _terminos_distintos(t for t in terminos if not _ambigua_en_pliego(t))
            < _MIN_TERMINOS_CATEGORIA
        ):
            continue
        weighted = sum(min(v, _TOPE_POR_TERMINO) for v in terminos.values())
        if weighted < _MIN_WEIGHTED_HITS:
            continue
        score = round(min(1.0, weighted / _SCORE_SATURATION), 4)
        results[tech] = TechSignal(score=score, matched_terms=sorted(terminos))
    return results


def _forma_canonica(casado: str, keywords: Iterable[str]) -> str:
    """La keyword del diccionario que nombra el texto casado.

    El patrón casa sin tildes y con plural, así que «COPIAS DE SEGURIDAD»
    puede venir de `copia de seguridad` o de `copias de seguridad`: se elige la
    más larga que casa entera, que es la que eligió la alternancia. Si ninguna
    casa (patrones y diccionario de versiones distintas) vale el texto casado.
    """
    candidatas = [kw for kw in keywords if patron_de_keyword(kw).fullmatch(casado)]
    if not candidatas:
        return casado
    return max(candidatas, key=lambda kw: len(plegar(kw))).lower()


def _terminos_distintos(terminos: Iterable[str]) -> int:
    """Cuántos términos **distintos** hay, contando como uno sus variantes.

    `copia de seguridad` y `copias de seguridad` son dos entradas del
    diccionario y una sola idea: sin esto, un pliego que dice las dos cumple
    la regla de «dos términos distintos» con un único concepto. Dos términos
    son el mismo si el patrón de uno casa entero con el otro, que es el mismo
    criterio (tildes, plural) con el que se casaron.
    """
    representantes: list[str] = []
    for termino in sorted(terminos, key=len):
        if not any(
            patron_de_keyword(r).fullmatch(termino) or patron_de_keyword(termino).fullmatch(r)
            for r in representantes
        ):
            representantes.append(termino)
    return len(representantes)


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
    # no persiste fila para un label con score 0.0 (services/ml/classifier_training.py) y
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

    # Desde v136 el resumen lo deriva el trigger de ``licitacion_tecnologia_score``
    # (predicha = ``probabilidad >= threshold_aplicado``), y el repositorio ya
    # no escribe las tres columnas. Para que «el merge nunca borra» siga siendo
    # verdad, una tecnología que el CSV daba por predicha y la tabla no (sin
    # fila, o con fila por debajo de su umbral: el camino de ingesta de
    # ``scraper/pipeline.py`` escribe el CSV sin filas de score) se **adopta**:
    # se persiste con ``threshold_aplicado`` igual a su propio score, que es
    # exactamente «predicha a este score». ``thresholds`` ausente = estado sin
    # umbrales leídos, y entonces no se adopta nada (llamadores anteriores).
    thresholds: dict[str, float] | None = state.get("thresholds")
    adopted_scores: list[tuple[str, float]] = []
    if thresholds is not None:
        for tech in sorted(existing_predicted - set(pliego_scores)):
            previo = existing_scores.get(tech)
            if previo is None or previo < thresholds.get(tech, float("inf")):
                adopted_scores.append((tech, previo or 0.0))

    return {
        "ml_tecnologias": ml_tecnologias,
        "ml_proba_max": ml_proba_max,
        "ml_tech_principal": ml_tech_principal,
        "pliego_scores": [(tech, full_scores[tech]) for tech in pliego_scores],
        "adopted_scores": adopted_scores,
        "threshold_aplicado": threshold_aplicado,
        "existing_scores": existing_scores,
        "full_scores": full_scores,
    }


def merge_doc_signals(licitacion_ids: list[str] | None = None) -> dict[str, int]:
    """Fusiona señales de pliego (``score >= PLIEGO_TECH_MIN_SCORE``) hacia
    ``ml_tecnologias``/``ml_proba_max``/``ml_tech_principal`` y hace upsert
    de las filas de ``licitacion_tecnologia_score`` que la señal tocó.

    Sin ``licitacion_ids``, cubre solo las licitaciones que lo NECESITAN
    (``list_signals_for_merge``: alguna señal sin ``merged_at``, o un resumen
    ML a NULL o que no contiene la tecnología detectada) -- uso del paso
    ``tech_signal_merge`` (``scheduler/pipeline_runs.py``, tras
    ``precompute_ml_tecnologias``, que reescribe las tres columnas resumen de
    lo que puntúa). Hasta 2026-09-14 barría TODAS las licitaciones con señal
    cada 4 h porque ``db/upsert.py`` las nuleaba en cada re-scrape; con las
    columnas ML en ``_LIC_COALESCE_UPDATE_FIELDS`` eso ya no pasa, y la
    pasada acotada deja el coste proporcional a lo que cambió. Con una lista,
    cubre exactamente esas -- uso tras puntuar un lote nuevo
    (``scheduler/jobs/documentos_embeddings.py``, ``llm_tech_labeling``).

    Idempotente y fail-open por licitación: para una licitación seleccionada
    no depende de ``merged_at`` para decidir si fusiona (siempre recalcula),
    solo lo usa para no reemitir el evento de auditoría en re-corridas. El
    merge nunca borra una tecnología ya predicha por el modelo, solo añade lo
    que el pliego detectó encima.

    Devuelve, además de lo fusionado y lo emitido, ``licitaciones_candidatas``
    (las que entraron en el lote) y ``licitaciones_reparadas`` (las del lote
    cuya señal ya estaba TODA estampada: en la pasada sin ids, cada una es un
    resumen ML que perdió una señal ya fusionada y hubo que reescribir). El
    paso de la pipeline los loguea; «cero reparaciones en siete días» se mide
    sobre ese contador.
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
    # Reparación = ninguna fila de la licitación quedaba por estampar. En la
    # pasada sin ids, la única forma de volver a salir es que el resumen ML
    # haya perdido la señal; es el contador del backlog («cero reparaciones
    # en siete días»), y se loguea aquí además de devolverse para que también
    # quede rastro cuando el llamador descarta el resultado.
    reparadas = sum(
        1 for rows in by_licitacion.values() if all(r.get("merged_at") is not None for r in rows)
    )
    log.info(
        "tech_signal_merge_candidates",
        modo="ids" if licitacion_ids else "pendientes",
        n_licitaciones=len(by_licitacion),
        n_reparaciones=reparadas,
    )
    if not by_licitacion:
        return {
            "licitaciones_merged": 0,
            "events_emitted": 0,
            "errors": 0,
            "licitaciones_candidatas": 0,
            "licitaciones_reparadas": 0,
        }

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
        "licitaciones_candidatas": len(by_licitacion),
        "licitaciones_reparadas": reparadas,
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
