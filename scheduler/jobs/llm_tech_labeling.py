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
- Una etiqueta cuya cita no aparece en el anuncio se descarta
  (``services.llm_tech_labeling.parse_labels``) y se cuenta en
  ``etiquetas_sin_evidencia``. Si el modelo afirmó tecnologías y **ninguna**
  sostuvo su cita, se escribe ``SIN_EVIDENCIA_SENTINEL`` y no el «sin
  tecnología»: la licitación queda procesada para esta versión (cuenta en
  ``sin_evidencia``) sin convertirse en un negativo falso, ni en el
  entrenamiento ni en ``ml_feedback``.
- El presupuesto se comprueba de forma *eager* antes de cada llamada: el
  ``check()`` que hace ``llm/client.py`` vive dentro del generador y no se
  evalúa hasta consumir el stream, lo que en un batch significaría descubrir
  el corte a mitad de item.
- Sin ``NVIDIA_API_KEY`` el provider no emite nada y ``classify_licitacion``
  lanza: la corrida cuenta N errores y no marca nada como procesado, que es
  una degradación visible en vez de silenciosa.
- Con la key **rechazada** (401/403) el provider lanza ``LLMAuthError`` y el
  lote se corta en el primer item: la misma key fallaría en todos los demás.
  La causa queda en ``counts["credencial_rechazada"]`` y llega así al mensaje
  del paso canónico, que es el cuerpo del email de alerta.
- Con el modelo **retirado** (404/410) el provider lanza
  ``LLMModelUnavailableError`` y el corte es el mismo, con la causa en
  ``counts["modelo_no_disponible"]``. Del 2026-09-21 al 2026-09-24 el cierre de
  ``scrape-daily`` estuvo en rojo por el 410 de ``deepseek-v4-flash-0731``, y
  el log solo decía «El LLM devolvió una respuesta vacía».
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
    from services.llm_tech_labeling import Clasificacion

log = get_logger(__name__)

# Etiqueta del feedback automático en ``ml_feedback.source``. El entrenamiento
# del SAPClassifier filtra por ``source = 'revision_ti'`` (el plan de
# clasificación en tres niveles; antes ``'human'``), así que estas filas (su
# ``relevante`` es ``es_ti``, no una tecnología concreta) vacían la cola de
# active learning sin realimentar al modelo con sus propias predicciones.
FEEDBACK_SOURCE = "llm_batch"


def _write_feedback(clasificadas: dict[str, Clasificacion], *, version: str) -> dict[str, int]:
    """Vuelca a ``ml_feedback`` la respuesta de nivel 1 (``es_ti``).

    Una fila de feedback saca la licitación de la cola humana para siempre (la
    query es un anti-join), así que ``relevante`` tiene que ser una respuesta
    real y no una inferencia: es ``clasificacion.es_ti`` tal cual, que desde
    esta tarea es lo único que ``relevante`` significa (spec §3.3) -- antes se
    derivaba de si «SAP» estaba entre las familias confiadas. Así que el
    ``relevante`` de las filas ``llm_batch`` mezcla los significados de v2 y v3
    y NO es una etiqueta de entrenamiento.

    Sin ``es_ti`` (``None``: el modelo no contestó el nivel 1, p. ej. una
    respuesta que se quedó en el prompt v2) no se escribe fila: es justo lo
    dudoso que merece un par de ojos humanos, no un ``relevante`` inventado.

    La tecnología principal y las secundarias siguen saliendo de
    ``clasificacion.scores`` con el mismo umbral de siempre
    (``LLM_TECH_FEEDBACK_MIN_CONF``): con ``es_ti=False`` ``scores`` ya llega
    vacío (nivel 1 lo fuerza en ``parse_labels``), y con familias por debajo
    del umbral ``tecnologia`` queda en ``None`` sin que eso bloquee la fila --
    a diferencia de antes, la confianza de la familia ya no decide si se
    escribe, solo qué principal lleva.
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

    for licitacion_id, clasificacion in clasificadas.items():
        if licitacion_id in ya_etiquetadas:
            counts["feedback_omitido"] += 1
            continue
        if clasificacion.es_ti is None:
            counts["feedback_omitido"] += 1
            continue
        es_ti: bool = clasificacion.es_ti
        seguras = {tech: s.score for tech, s in clasificacion.scores.items() if s.score >= umbral}
        principal = max(seguras, key=lambda t: seguras[t]) if seguras else None
        try:
            repo.insert(
                expediente=licitacion_id,
                relevante=es_ti,
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

    Una licitación cuyas etiquetas no sostuvieron su cita (``sin_evidencia``)
    también es progreso: el proveedor respondió y quedó procesada.
    """
    procesadas = counts["scored"] or counts["no_signal"] or counts.get("sin_evidencia", 0)
    return bool(counts["error"]) and not procesadas


def run() -> dict[str, Any]:
    """Clasifica un lote de licitaciones pendientes. Fail-open por item."""
    from config import settings

    counts: dict[str, Any] = {
        "scored": 0,
        "no_signal": 0,
        # Licitaciones: todas sus etiquetas cayeron por falta de cita.
        "sin_evidencia": 0,
        # Etiquetas: descartadas por falta de cita, en cualquier licitación.
        "etiquetas_sin_evidencia": 0,
        "error": 0,
        "disabled": 0,
        "budget_exhausted": 0,
        "merged": 0,
        "feedback_escrito": 0,
        "feedback_omitido": 0,
        # Respuesta a la pregunta de nivel 1 (``es_ti``), aparte del recuento
        # de familias de arriba: ``es_ti_sin_respuesta`` es una respuesta v2
        # (o cualquiera sin el campo), no un error.
        "es_ti_si": 0,
        "es_ti_no": 0,
        "es_ti_sin_respuesta": 0,
    }
    if not settings.LLM_TECH_LABELING_ENABLED:
        counts["disabled"] = 1
        return counts

    from db.repositories.tecnologia_pliego import (
        ES_TI_SENTINEL,
        NO_ES_TI_SENTINEL,
        TechSignal,
        TecnologiaPliegoRepository,
    )
    from llm.budget import LLMBudgetExceeded, get_budget_guard
    from llm.providers import LLMAuthError, LLMModelUnavailableError
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
    clasificadas: dict[str, Clasificacion] = {}

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
            clasificacion = classify_licitacion(lic, model=model)
            if clasificacion.scores:
                status = "scored"
            elif clasificacion.sin_evidencia:
                status = "sin_evidencia"
            else:
                status = "no_signal"
            # Familias y marcador de nivel 1 van en la MISMA llamada, en el
            # MISMO ``method=METHOD`` (``llm_metadata``): la CHECK
            # ``ck_lic_tec_pliego_method`` de la tabla no admite un
            # ``method`` propio para el marcador sin migración (F5), y
            # ``upsert_signals`` borra por ``method`` -- dos llamadas se
            # pisarían la una a la otra en vez de sumarse.
            filas: dict[str, TechSignal] = dict(clasificacion.scores)
            if clasificacion.es_ti is not None:
                marcador = ES_TI_SENTINEL if clasificacion.es_ti else NO_ES_TI_SENTINEL
                filas[marcador] = TechSignal(
                    score=0.0,
                    evidence=[
                        {
                            "es_ti": clasificacion.es_ti,
                            "confianza": clasificacion.confianza_es_ti,
                            "otros_fabricantes": list(clasificacion.otros_fabricantes),
                        }
                    ],
                )
            repo.upsert_signals(
                licitacion_id,
                method=METHOD,
                signal_version=version,
                scores=filas,
                sin_evidencia=status == "sin_evidencia",
            )
        except LLMAuthError as exc:
            # La key rechazada lo será igual para todo lo que queda del lote:
            # seguir solo repetiría la misma llamada fallida (el run
            # 34517205501 hizo 200). Se corta aquí y la causa viaja en el
            # recuento, que es lo que acaba en el mensaje del paso y su email.
            counts["error"] += 1
            counts["credencial_rechazada"] = str(exc)
            pliego_tech_signal_total.labels(method=METHOD, status="error").inc()
            log.error(
                "llm_tech_labeling_auth_rejected",
                licitacion_id=licitacion_id,
                pendientes_sin_procesar=len(pendientes) - len(procesadas),
                error=str(exc),
            )
            break
        except LLMModelUnavailableError as exc:
            # Mismo corte que la key: el modelo retirado falla igual en todo lo
            # que queda, y la causa tiene que llegar al email con su nombre.
            counts["error"] += 1
            counts["modelo_no_disponible"] = str(exc)
            pliego_tech_signal_total.labels(method=METHOD, status="error").inc()
            log.error(
                "llm_tech_labeling_model_unavailable",
                licitacion_id=licitacion_id,
                pendientes_sin_procesar=len(pendientes) - len(procesadas),
                error=str(exc),
            )
            break
        except Exception as exc:
            counts["error"] += 1
            pliego_tech_signal_total.labels(method=METHOD, status="error").inc()
            log.warning("llm_tech_labeling_failed", licitacion_id=licitacion_id, error=str(exc))
            continue
        procesadas.append(licitacion_id)
        # Una licitación sin evidencia no va al feedback: su lista vacía no es
        # un «no relevante», es justo lo dudoso que merece ojos humanos.
        if status != "sin_evidencia":
            clasificadas[licitacion_id] = clasificacion
        counts[status] += 1
        counts["etiquetas_sin_evidencia"] += len(clasificacion.sin_evidencia)
        if clasificacion.es_ti is True:
            counts["es_ti_si"] += 1
        elif clasificacion.es_ti is False:
            counts["es_ti_no"] += 1
        else:
            counts["es_ti_sin_respuesta"] += 1
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
