"""Job batch: categorización de licitaciones por LLM sobre la metadata.

Etiquetar a mano la cola de active learning (``/ops?vista=etiquetado``) es
inviable con el volumen del corpus. Este job recorre las licitaciones sin
señal LLM vigente, las clasifica con el proveedor configurado
(``LLM_TECH_LABELING_MODEL``, NVIDIA por defecto) leyendo solo el anuncio, y
funde el resultado hacia ``licitaciones.ml_tecnologias``.

Contratos de fallo (importantes para no corromper el estado):

- Un error de clasificación **no** persiste señal, así que la licitación
  vuelve a salir pendiente en la siguiente corrida. Solo una respuesta válida
  con lista vacía escribe el sentinel "sin tecnología".
- El presupuesto se comprueba de forma *eager* antes de cada llamada: el
  ``check()`` que hace ``llm/client.py`` vive dentro del generador y no se
  evalúa hasta consumir el stream, lo que en un batch significaría descubrir
  el corte a mitad de item.
- Sin ``NVIDIA_API_KEY`` el provider no emite nada y ``classify_licitacion``
  lanza: la corrida cuenta N errores y no marca nada como procesado, que es
  una degradación visible en vez de silenciosa.
- Si el lote entero se cae, ``batch_failed_systemically`` lo detecta y el paso
  canónico lanza, de forma que ``_run_periodic`` suelte la ventana diaria y la
  siguiente pasada reintente en vez de dar el día por consumido.

Caveat de presupuesto (mismo que la fase de facts): los runners de Actions no
propagan ``REDIS_URL``, así que el acumulador del ``BudgetGuard`` arranca de 0
en cada corrida. El tope real de gasto por corrida es
``LLM_TECH_LABELING_BATCH``, no la ventana diaria.

Los dos carriles de ingesta (``scrape-daily.yml`` y ``scrape-bulk.yml``) llevan
``NVIDIA_API_KEY`` y los flags en el ``env:`` de su step, porque ambos ejecutan
los pasos post-ingesta y el lock diario lo toma el primero que llegue.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from observability.logging import get_logger

if TYPE_CHECKING:
    from db.repositories.tecnologia_pliego import TechSignal

log = get_logger(__name__)

# Etiqueta del feedback automático en ``ml_feedback.source``. El entrenamiento
# del SAPClassifier filtra por ``source = 'human'``, así que estas filas vacían
# la cola de active learning sin realimentar al modelo con sus predicciones.
FEEDBACK_SOURCE = "llm_batch"


def _write_feedback(
    clasificadas: dict[str, dict[str, TechSignal]], *, version: str
) -> dict[str, int]:
    """Vuelca a ``ml_feedback`` las etiquetas lo bastante seguras.

    Una fila de feedback saca la licitación de la cola humana para siempre (la
    query es un anti-join), así que solo se escriben los casos claros:

    - el LLM devolvió tecnologías y la principal supera
      ``LLM_TECH_FEEDBACK_MIN_CONF``;
    - o el LLM no vio ninguna tecnología, que en un corpus donde la mayoría de
      los anuncios no son de TI es la respuesta masiva y de bajo riesgo.

    Lo dudoso (tecnologías por debajo del umbral) se deja sin fila: es
    exactamente lo que merece un par de ojos humanos.
    """
    from config import settings
    from db.repositories.feedback import FeedbackRepository

    counts = {"feedback_escrito": 0, "feedback_omitido": 0}
    if not settings.LLM_TECH_FEEDBACK_ENABLED or not clasificadas:
        return counts

    repo = FeedbackRepository()
    # ml_feedback no tiene unique sobre expediente: sin este filtro, una
    # re-corrida (bump de signal_version) duplicaría filas contradictorias.
    ya_etiquetadas = repo.existing_expedientes(list(clasificadas))
    umbral = settings.LLM_TECH_FEEDBACK_MIN_CONF

    for licitacion_id, scores in clasificadas.items():
        if licitacion_id in ya_etiquetadas:
            counts["feedback_omitido"] += 1
            continue
        seguras = {tech: s.score for tech, s in scores.items() if s.score >= umbral}
        if scores and not seguras:
            counts["feedback_omitido"] += 1
            continue
        principal = max(seguras, key=lambda t: seguras[t]) if seguras else None
        try:
            repo.insert(
                expediente=licitacion_id,
                relevante="SAP" in seguras,
                nota=f"{FEEDBACK_SOURCE}:{version}",
                tecnologia=principal,
                tecnologias_secundarias=sorted(t for t in seguras if t != principal),
                source=FEEDBACK_SOURCE,
            )
        except Exception as exc:
            counts["feedback_omitido"] += 1
            log.warning(
                "llm_tech_feedback_insert_failed", licitacion_id=licitacion_id, error=str(exc)
            )
            continue
        counts["feedback_escrito"] += 1
    return counts


def batch_failed_systemically(counts: dict[str, Any]) -> bool:
    """True si se intentó clasificar y **nada** salió bien.

    Un anuncio que el modelo no sabe leer es normal y se cuenta como error
    suelto; que no quede ni una clasificación en todo el lote no lo es: falta
    la API key, la red está caída o el proveedor devuelve basura. Los dos
    entrypoints lo usan para decir "esto no ha funcionado" en vez de reportar
    una corrida limpia de cero resultados.
    """
    return bool(counts["error"]) and not counts["scored"] and not counts["no_signal"]


def run() -> dict[str, Any]:
    """Clasifica un lote de licitaciones pendientes. Fail-open por item."""
    from config import settings

    counts: dict[str, Any] = {
        "scored": 0,
        "no_signal": 0,
        "error": 0,
        "disabled": 0,
        "budget_exhausted": 0,
        "merged": 0,
        "feedback_escrito": 0,
        "feedback_omitido": 0,
    }
    if not settings.LLM_TECH_LABELING_ENABLED:
        counts["disabled"] = 1
        return counts

    from db.repositories.tecnologia_pliego import TecnologiaPliegoRepository
    from llm.budget import LLMBudgetExceeded, get_budget_guard
    from observability.ops_events import record_event
    from observability.runtime_metrics import pliego_tech_signal_total
    from services.llm_tech_labeling import METHOD, classify_licitacion, signal_version
    from services.tech_signal import merge_doc_signals

    model = settings.LLM_TECH_LABELING_MODEL
    version = signal_version(model)
    repo = TecnologiaPliegoRepository()
    guard = get_budget_guard()

    pendientes = repo.list_metadata_pending_llm_signal(
        signal_version=version, method=METHOD, limit=settings.LLM_TECH_LABELING_BATCH
    )
    procesadas: list[str] = []
    clasificadas: dict[str, dict[str, TechSignal]] = {}

    for lic in pendientes:
        licitacion_id = str(lic["id_externo"])
        try:
            guard.check()
        except LLMBudgetExceeded as exc:
            counts["budget_exhausted"] = 1
            log.warning(
                "llm_tech_labeling_budget_exhausted",
                window=exc.window,
                pendientes_sin_procesar=len(pendientes) - len(procesadas),
            )
            break
        try:
            scores = classify_licitacion(lic, model=model)
            repo.upsert_signals(licitacion_id, method=METHOD, signal_version=version, scores=scores)
        except Exception as exc:
            counts["error"] += 1
            pliego_tech_signal_total.labels(method=METHOD, status="error").inc()
            log.warning("llm_tech_labeling_failed", licitacion_id=licitacion_id, error=str(exc))
            continue
        procesadas.append(licitacion_id)
        clasificadas[licitacion_id] = scores
        status = "scored" if scores else "no_signal"
        counts[status] += 1
        pliego_tech_signal_total.labels(method=METHOD, status=status).inc()

    if procesadas:
        merge_result = merge_doc_signals(licitacion_ids=procesadas)
        counts["merged"] = merge_result["licitaciones_merged"]

    counts.update(_write_feedback(clasificadas, version=version))

    record_event("llm_tech_labeling", value=float(counts["scored"]), detail=json.dumps(counts))
    log.info("llm_tech_labeling_done", model=model, **counts)
    return counts


# ── CLI ───────────────────────────────────────────────────────────────────────
#
# Drenado manual del backlog: ``python -m scheduler.jobs.llm_tech_labeling``
# con ``LLM_TECH_LABELING_BATCH`` subido procesa un lote grande de una vez.


def run_cli() -> int:
    """Corre el job; falla solo si el lote entero se cayó.

    Un anuncio que el modelo no sabe clasificar es normal; que **ningún** item
    del lote se procese señala algo sistémico (falta la API key, red caída,
    presupuesto agotado desde el primer item) que sí debe romper el workflow.
    """
    from db.database import init_db

    init_db()
    resumen = run()

    if batch_failed_systemically(resumen):
        log.error("llm_tech_labeling_cli_batch_failed", **resumen)
        return 1
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(run_cli())
