"""Implementación de cada paso canónico de la pipeline (``_run_<paso>``).

Un ``_run_<nombre>`` por entrada de ``CANONICAL_STEPS``
(``scheduler.pipeline_pasos``). El ejecutor (``scheduler.pipeline_cierre``) los
resuelve por nombre contra **este** módulo, que es por tanto el que se parchea
en los tests para sustituir un paso.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger
from observability.ops_events import record_event
from scheduler.pipeline_pasos import (
    LANE_BULK,
    LANE_DAILY,
    STEP_OK,
    STEP_SKIPPED,
    _contar_error,
)

# El nombre de antes de partir el módulo: `logger` sale en cada línea de log.
log = get_logger("scheduler.pipeline_runs")

#: Tipo de evento con el que ``tech_signal_merge`` deja en ``ops_events`` las
#: reparaciones de cada pasada. Es la serie que mide su criterio de retirada.
EVENTO_TECH_SIGNAL_MERGE = "tech_signal_merge"


# ---------------------------------------------------------------------------
# Pasos periódicos (cadencia propia dentro de la pipeline de 4h)
# ---------------------------------------------------------------------------

_SEGUNDOS_DIA = 24 * 60 * 60
_SEGUNDOS_SEMANA = 7 * _SEGUNDOS_DIA


def _run_periodic(name: str, ttl_seconds: int, fn: Any) -> str:
    """Ejecuta ``fn`` como mucho una vez cada ``ttl_seconds``.

    La pipeline canónica corre cada 4h, pero algunos pasos tienen cadencia
    propia (un digest "diario" enviado 6 veces al día no es diario). Se
    reutiliza ``db.job_locks`` con el periodo como TTL: el lock **no se
    libera** al terminar bien, así que actúa de ventana temporal — las
    siguientes pasadas dentro del periodo no lo adquieren y se saltan el paso.

    Si ``fn`` falla se libera el lock para que la siguiente pasada (4h más
    tarde) reintente, en vez de perder la ventana entera.

    Returns:
        ``"ok"`` si se ejecutó, ``"skipped"`` si aún no tocaba.
    """
    from db.job_locks import acquire, release

    holder = "pipeline_runs"
    if not acquire(name, ttl_seconds=ttl_seconds, holder=holder):
        log.debug("pipeline_periodic_skipped", step=name)
        return "skipped"

    try:
        fn()
    except Exception:
        release(name, holder=holder)
        raise
    return "ok"


def _run_ml_scoring() -> str:
    """Score keyword-route licitaciones (ml_proba IS NULL).

    Sin try/except propio: hasta 2026-08 tragaba cualquier excepción a nivel
    debug y reportaba "ok" al ejecutor, así que un scoring roto era invisible.
    El ejecutor canónico ya aísla y alerta los fallos de cada paso.

    **Propaga el resultado del precompute** (2026-09). Hasta ahora este paso
    reportaba ``ok`` pasara lo que pasara, y eso tapaba un acoplamiento real:
    ``precompute_ml_proba`` solo comprobaba ``SAPClassifier.is_available()`` —un
    ``Path.exists()`` sobre el disco del runner— y si no había artefacto
    devolvía ``{"updated": 0, "skipped_no_model": True}`` sin puntuar nada. El
    fichero solo estaba ahí si la ingesta previa, en el MISMO runner, lo había
    descargado. Hoy el precompute y la ingesta resuelven el artefacto cada uno
    por ``SAPClassifier.resolve_artifact()``, que lo baja si falta.

    Clave del dict que se lee: ``skipped_no_model`` (bool). Si esa clave
    desapareciera del dict, este paso reportaría ``ok`` sin modelo — por eso
    el nombre va documentado aquí y no solo leído.

    Returns:
        ``"ok"`` si el precompute puntuó (o no tenía nada que puntuar),
        ``"skipped"`` si reportó que no hay modelo disponible.
    """
    from services.ml.classifier_training import precompute_ml_proba

    resultado = precompute_ml_proba(force=False)
    if resultado.get("skipped_no_model"):
        log.warning(
            "pipeline_ml_scoring_sin_modelo",
            detalle=(
                "precompute_ml_proba devolvió skipped_no_model: el artefacto del "
                "clasificador SAP no está en el disco de este runner. Ninguna "
                "licitación nueva quedó puntuada en esta pasada."
            ),
        )
        return STEP_SKIPPED
    return STEP_OK


def _run_ml_tecnologias() -> str:
    """Multi-technology scoring (feature-flagged).

    Sin try/except propio por el mismo motivo que ``_run_ml_scoring``, y
    propaga el resultado por el mismo motivo: ``precompute_ml_tecnologias``
    también devuelve ``skipped_no_model`` cuando ``TechnologyClassifier`` no
    está en el disco del runner.

    Returns:
        ``"skipped"`` si el flag ``ML_TECH_ENABLED`` está apagado o si el
        precompute reporta que no hay modelo; ``"ok"`` en caso contrario.
    """
    from config import settings as _settings

    if not getattr(_settings, "ML_TECH_ENABLED", False):
        return STEP_SKIPPED

    from services.ml.classifier_training import precompute_ml_tecnologias

    resultado = precompute_ml_tecnologias(force=False)
    if resultado.get("skipped_no_model"):
        log.warning(
            "pipeline_ml_tecnologias_sin_modelo",
            detalle=(
                "precompute_ml_tecnologias devolvió skipped_no_model: el "
                "artefacto multi-tecnología no está en el disco de este runner."
            ),
        )
        return STEP_SKIPPED
    return STEP_OK


def _run_tech_signal_merge() -> None:
    """Fusiona la señal de pliego que el resumen ML aún no refleja.

    Sin ids, ``merge_doc_signals`` ya no barre todas las licitaciones con
    señal: ``list_signals_for_merge`` selecciona solo las que tienen alguna
    señal sin ``merged_at`` o cuyo resumen (``ml_tecnologias``/
    ``ml_proba_max``/``ml_tech_principal``) está a NULL o no contiene la
    tecnología detectada. Desde 2026-09-14 las cuatro columnas ML están en
    ``_LIC_COALESCE_UPDATE_FIELDS`` (``db/upsert.py``), así que una re-ingesta
    ya no las nulea; lo que queda por sanar aquí son los caminos que
    reescriben el resumen por UPDATE explícito sin la señal:
    ``precompute_ml_tecnologias`` (paso anterior; con ``force=True`` toca todas
    las filas, sin él solo las que tienen ``ml_proba_max IS NULL``) y cualquier
    limpieza manual. Fail-open por licitación -- no hace falta ``try/except``
    aquí porque ``merge_doc_signals`` ya captura y cuenta los fallos.

    El resultado se loguea en vez de descartarse: este paso se comió 14 de los
    20 minutos del step de cierre durante días (una transacción por licitación,
    ver ``merge_many_with_lock``) y desde fuera era invisible -- ni duración ni
    recuento de errores, solo un warning suelto por licitación rota. Con
    ``elapsed_ms`` y ``errors`` en el log, la próxima deriva se ve en el propio
    runner. ``licitaciones_reparadas`` es el contador con el que se mide el
    cierre del ítem del backlog («cero reparaciones en siete días»): cada
    unidad es una licitación cuya señal ya estaba fusionada y cuyo resumen
    hubo que reescribir.

    Ese contador va también a ``ops_events``: el criterio de retirada se mide
    ahí y el paso solo lo dejaba en el log del runner, que GitHub Actions
    borra a los 90 días y nadie consulta con SQL. Solo lo emite esta pasada
    sin ids; la de ``llm_tech_labeling`` (con ids) cuenta como «reparadas» las
    licitaciones ya fusionadas que reetiqueta, que no son reparaciones.
    """
    import json
    import time as _time

    from services.tech_signal import merge_doc_signals

    t0 = _time.monotonic()
    result = merge_doc_signals()
    elapsed_ms = int((_time.monotonic() - t0) * 1000)
    log.info("pipeline_tech_signal_merge_completed", elapsed_ms=elapsed_ms, **result)
    record_event(
        EVENTO_TECH_SIGNAL_MERGE,
        value=float(result.get("licitaciones_reparadas", 0)),
        detail=json.dumps({**result, "elapsed_ms": elapsed_ms}, sort_keys=True),
    )


def _run_llm_tech_labeling() -> str:
    """Categorización por LLM sobre la metadata del anuncio (una vez al día).

    Va después de ``tech_signal_merge`` para no competir con él por la misma
    licitación en la misma pasada: el job funde su propio lote al terminar, y
    ese merge incremental es el que deja la señal en ``ml_tecnologias``.

    Cadencia diaria y no cada 4h porque cada corrida cuesta dinero real
    (``LLM_TECH_LABELING_BATCH`` llamadas al proveedor). Gated además por
    ``LLM_TECH_LABELING_ENABLED``, que por defecto deja el paso en no-op.

    Si el lote entero se cae —falta ``NVIDIA_API_KEY``, proveedor caído— se
    lanza a propósito: ``_run_periodic`` solo suelta la ventana cuando el paso
    falla, así que tragarse el fallo dejaría la cadencia diaria consumida sin
    haber clasificado nada. Lanzando, el paso sale en rojo (con su email) y la
    siguiente pasada de la pipeline, 4h después, lo reintenta.

    El lote va acotado por ``LLM_TECH_LABELING_BUDGET_S``: comparte el step de
    cierre con los pasos que vienen detrás, y un proveedor lento no puede
    dejarlos sin correr (#581).
    """
    from config import settings as _settings
    from scheduler.jobs.llm_tech_labeling import batch_failed_systemically
    from scheduler.jobs.llm_tech_labeling import run as run_llm_tech_labeling

    def _run_and_check() -> None:
        counts = run_llm_tech_labeling(presupuesto_s=float(_settings.LLM_TECH_LABELING_BUDGET_S))
        if batch_failed_systemically(counts):
            raise RuntimeError(f"El lote de etiquetado por LLM falló entero: {counts}")

    return _run_periodic("llm_tech_labeling", _SEGUNDOS_DIA, _run_and_check)


def _run_organos_resolve() -> str:
    """Resuelve ``organo_id`` de las grafías nuevas (ADR-032 §C, 2026-09-14).

    Hasta esta fecha solo el backfill de órganos (ya retirado) llamaba al resolutor,
    así que cada pasada del ATOM dejaba filas nuevas sin órgano y el maestro
    se degradaba solo. Acotado por cuenta y por reloj (settings
    ``ORGANOS_RESOLVE_*``): el backlog grande sigue siendo del script.
    """
    from config import settings as _settings
    from services.organos import resolver_pendientes

    resumen = resolver_pendientes(
        max_grafias=int(_settings.ORGANOS_RESOLVE_MAX_GRAFIAS),
        presupuesto_s=float(_settings.ORGANOS_RESOLVE_BUDGET_S),
    )
    log.info("pipeline_organos_resolve_completed", **resumen.as_dict())
    return STEP_OK if resumen.grafias_vistas else STEP_SKIPPED


def _run_analytics_export() -> None:
    """Snapshot Parquet + manifest de linaje (RFC-086). Best-effort.

    ``db.analytics`` adjunta la BD Postgres con el ``postgres_scanner`` de
    DuckDB. El paso sigue siendo best-effort —DuckDB es dependencia opcional y
    la extensión puede no estar disponible— pero un fallo se registra a
    **warning**, no a debug: un paso que no hace nada tiene que verse en los
    logs, que es exactamente el modo de fallo silencioso que ADR-021 vino a
    eliminar.
    """
    try:
        from db.analytics import run_analytics_export

        run_analytics_export()
    except Exception as exc:
        _contar_error("analytics_export")
        log.warning("pipeline_analytics_export_failed", error=str(exc), exc_info=True)


def _run_kpi_precompute() -> dict[str, Any]:
    from scheduler.kpi_precompute import run_kpi_precompute

    result = run_kpi_precompute()
    log.info(
        "pipeline_kpi_precompute_completed",
        n_metricas=result.get("n_metricas"),
        elapsed_ms=result.get("elapsed_ms"),
    )
    return result


def _run_aggregates_precompute() -> dict[str, Any]:
    from scheduler.aggregates_precompute import run_aggregates_precompute

    result = run_aggregates_precompute()
    log.info(
        "pipeline_aggregates_precompute_completed",
        n_clusters=result.get("n_clusters"),
    )
    return result


def _run_watchlist_notify() -> None:
    from scheduler.watchlist_alerts import check_and_notify

    check_and_notify()
    # Alertas de movimientos de competidores (watchlist por empresa, v36)
    try:
        from scheduler.competitor_alerts import check_and_notify as check_competitors

        check_competitors()
    except Exception as e:
        _contar_error("avisos_competidores")
        log.warning("competitor_alerts_failed", error=str(e), exc_info=True)
    # Alertas de reglas de watchlist por criterio (mi-watchlist, v43)
    try:
        from scheduler.watchlist_rules_alerts import check_rules_and_notify

        check_rules_and_notify()
    except Exception as e:
        _contar_error("avisos_reglas_watchlist")
        log.warning("watchlist_rules_alerts_failed", error=str(e), exc_info=True)
    # Recordatorios de plazo (favoritos y pursuits). Existían desde la Feature D
    # y nadie los invocaba desde ningún plano: en producción nunca corrieron.
    try:
        from services.deadline_reminders import check_all_users_deadlines

        check_all_users_deadlines()
    except Exception as e:
        _contar_error("recordatorios_plazo")
        log.warning("deadline_reminders_failed", error=str(e), exc_info=True)
    # Cierre asistido: oportunidades abiertas cuyo expediente ya se adjudicó.
    try:
        from services.pursuit_awards import notify_detected_awards

        notify_detected_awards()
    except Exception as e:
        _contar_error("adjudicaciones_oportunidades")
        log.warning("pursuit_awards_failed", error=str(e), exc_info=True)
    # Puntuaciones del acta de la mesa: encola la lectura de las que faltan en
    # los expedientes que alguien sigue y ya se adjudicaron (post-mortem de una
    # oportunidad perdida). Va tras el aviso porque es su misma población.
    try:
        from services.puntuaciones_acta import encolar_pendientes

        encolar_pendientes()
    except Exception as e:
        _contar_error("puntuaciones_acta")
        log.warning("puntuaciones_acta_failed", error=str(e), exc_info=True)


#: Horas locales (Madrid) en las que se entregan los digests diario y semanal:
#: la pasada de las 04:00/08:00 UTC según la estación. Un digest que llega a
#: las tres de la tarde no es «el correo de la mañana» que alguien abre con el
#: café, y con la cadencia de 4 h el momento de entrega derivaba de una pasada
#: a otra hasta caer en cualquier hora.
_VENTANA_MATINAL_HORAS = (6, 12)
#: Margen bajo el periodo del lock para que la ventana del día siguiente lo
#: encuentre libre aunque el cron llegue unos minutos antes que ayer.
_MARGEN_VENTANA_SEGUNDOS = 4 * 60 * 60


def _es_ventana_matinal(ahora: Any | None = None) -> bool:
    """¿Estamos en la franja de entrega de la mañana, hora peninsular?"""
    from datetime import UTC, datetime, timedelta, timezone

    momento = ahora or datetime.now(UTC)
    try:
        from zoneinfo import ZoneInfo

        local = momento.astimezone(ZoneInfo("Europe/Madrid"))
    # Sin tzdata: aproximar con el horario de invierno. `ZoneInfoNotFoundError`
    # es un `KeyError`; el `ImportError` cubre un intérprete sin `zoneinfo`.
    except (ImportError, KeyError):
        local = momento.astimezone(timezone(timedelta(hours=1)))
    inicio, fin = _VENTANA_MATINAL_HORAS
    return inicio <= local.hour < fin


def _run_digests() -> dict[str, str]:
    """Drena ``pending_digests`` para las tres frecuencias.

    ``_run_watchlist_notify`` (arriba) **acumula** las coincidencias en
    ``pending_digests`` con la frecuencia de cada regla; este paso las envía:

    - ``immediate``: en cada pasada, sin ventana ni lock. Hasta 2026-09 estas
      filas se encolaban y **nunca** se enviaban: ``send_pending_digests`` sólo
      admitía daily/weekly y aquí sólo se invocaban esas dos.
    - ``daily`` y ``weekly``: una vez por periodo y sólo en la ventana matinal
      (:func:`_es_ventana_matinal`), para que el digest sea el correo de la
      mañana y no el de la pasada que casualmente cumplía las 24 h.

    Antes de 2026-08 ni daily ni weekly se enviaban en producción, porque
    ``send_pending_digests`` sólo estaba registrado en el plano APScheduler,
    que no es el plano activo (ADR-012).
    """
    from scheduler.watchlist_alerts import send_pending_digests

    resultado: dict[str, str] = {}
    send_pending_digests("immediate")
    resultado["immediate"] = "ok"
    if not _es_ventana_matinal():
        log.debug("pipeline_digests_fuera_de_ventana")
        resultado["daily"] = "skipped"
        resultado["weekly"] = "skipped"
        return resultado
    resultado["daily"] = _run_periodic(
        "digest_daily",
        _SEGUNDOS_DIA - _MARGEN_VENTANA_SEGUNDOS,
        lambda: send_pending_digests("daily"),
    )
    resultado["weekly"] = _run_periodic(
        "digest_weekly",
        _SEGUNDOS_SEMANA - _MARGEN_VENTANA_SEGUNDOS,
        lambda: send_pending_digests("weekly"),
    )
    return resultado


def _run_event_dispatch() -> str:
    """Reparte el outbox de ``domain_events`` (S4.1, ADR-027).

    Va después de ``watchlist_notify`` —que escribe los eventos de reglas y de
    competidores— y antes de ``digests``: el despachador encola en
    ``pending_digests`` los avisos en modo ``daily``, y así el digest de esta
    misma pasada ya los incluye. Sin dependencia declarada en ``STEP_DEPS``: un
    fallo de ``watchlist_notify`` no impide repartir lo que otros productores
    (oportunidades, tareas, cambios de expediente) dejaron en la cola.

    ``EVENT_DISPATCH_ENABLED=0`` lo apaga sin desplegar (``skipped``).
    """
    from config.settings import event_dispatch_enabled

    if not event_dispatch_enabled():
        log.info("pipeline_event_dispatch_desactivado")
        return STEP_SKIPPED
    from scheduler.jobs.event_dispatch import run as run_event_dispatch

    procesados = run_event_dispatch()
    log.info("pipeline_event_dispatch_completed", procesados=procesados)
    return STEP_OK


def _run_informes_programados() -> str:
    """Envía los informes semanales cuya ventana está abierta (T6).

    Sin cadencia propia (`_run_periodic`) y eso es deliberado: la cadencia la
    pone cada organización en `organization_report_schedules`, y el filtro de
    «ya enviado en esta ventana» vive en el SQL del repositorio. Envolverlo
    además en un lock de periodo global haría que dos organizaciones con la
    misma hora compitieran por él y una se quedara sin informe.
    """
    from scheduler.jobs.informes_programados import ejecutar

    resumen = ejecutar()
    log.info("pipeline_informes_programados_completed", **resumen.as_dict())
    return STEP_OK if resumen.programadas else STEP_SKIPPED


def _run_retention_cleanup() -> str:
    """Purga histórico según la política de retención (una vez al día)."""
    from scheduler.jobs.retention_cleanup import run as run_retention_cleanup

    return _run_periodic("retention_cleanup", _SEGUNDOS_DIA, run_retention_cleanup)


def _run_sap_active_learning() -> str:
    """Active learning del clasificador SAP (una vez por semana).

    ``maybe_retrain_classifier`` (feedback ≥50) estaba implementado y testeado
    pero SIN ningún caller de producción: el feedback se acumulaba en
    ``ml_feedback`` para un contador de UI y nada lo consumía (revisión de
    arquitectura 2026-08). La función no-opea por debajo del umbral, así que la
    ventana semanal solo limita el coste del conteo.

    **Lanza, no entrena** (2026-10). Por encima del umbral encola
    ``ml-entrenar.yml`` (modelo ``sap``) —el único camino que entrena, publica y solo entonces
    activa— o, si no puede, avisa con el comando. Hasta entonces entrenaba y
    activaba la versión aquí mismo, en un runner que se destruye al acabar el
    job, con un aviso en el log como único recordatorio de subir el ``.pkl`` a
    la Release. El 2026-09-29 ese aviso ni llegó a escribirse: el
    ``precompute_ml_proba(force=True)`` posterior agotó los 20 minutos del
    step, y la versión quedó activa sin artefacto. Como este paso ya no puede
    activar nada, el aviso se retiró con el camino que lo necesitaba.
    """

    def _run() -> None:
        from scheduler.concept_drift import maybe_retrain_classifier

        maybe_retrain_classifier()

    return _run_periodic("sap_active_learning", _SEGUNDOS_SEMANA, _run)


def _run_drift_checks() -> str:
    """Informe de drift + monitor con alertas (una vez por semana).

    Dos piezas complementarias que hasta ahora no corrían en ningún plano
    activo: ``run_drift_report`` deja el informe de drift de features, y
    ``drift_monitor.run_once`` calcula PSI + caída de F1 y **notifica** si
    superan umbral — la única detección de degradación de modelo del sistema.
    """

    def _both() -> None:
        from scheduler.drift_monitor import run_once
        from scheduler.drift_report import run_drift_report

        run_drift_report()
        run_once()

    return _run_periodic("drift_checks", _SEGUNDOS_SEMANA, _both)


def _run_dlq_retry(lane: str = LANE_BULK) -> None:
    """Drena la DLQ. En el carril diario **no** reintenta meses bulk.

    Una entrada ``bulk_YYYYMM`` se reintenta corriendo ``PlacspBulkConnector``
    para ese mes: la descarga y el reparseo de los ZIP de un mes entero, más su
    resolución de entidades. Con la DLQ arrastrando varios meses, ese trabajo se comía el
    presupuesto entero del job diario y GitHub lo cancelaba a mitad de la
    cadena post-ingesta (runs de 2026-08-01/03: cancelados dentro de
    ``dlq_retry`` reprocesando siete ficheros ``...Completo3_2026MM....atom``).
    El diario deja de tocarlas y las cubre `scrape-bulk.yml`, que es donde
    reprocesar meses tiene sentido y presupuesto.
    """
    from scheduler.dlq_retry import retry_failed_extractions

    retry_failed_extractions(include_bulk=lane != LANE_DAILY)


def _run_webhook_reintentos() -> dict[str, Any]:
    """Reenvía las entregas de webhook pendientes (C2.4).

    Sin cadencia propia: cada pasada drena lo que venció, y lo que no entre en
    el tope sale en la siguiente.
    """
    from scheduler.jobs.webhook_reintentos import run as run_webhook_reintentos

    return run_webhook_reintentos()


def _run_anomaly_checks() -> None:
    from scheduler.anomaly_alerts import run_anomaly_checks

    run_anomaly_checks()


def _run_cartera_avisos() -> str:
    """F4.3 — cartera de contratos: resincroniza y avisa del fin, una vez al día.

    Primero lleva a la cartera las oportunidades ganadas y lo que cambió desde
    ayer (una prórroga que ``contract_events`` registró mueve la fecha de fin),
    y después escribe en el outbox los avisos a seis, tres y un mes. En ese
    orden, para que el aviso salga con la fecha ya movida.
    """
    from services.cartera import emitir_avisos_de_fin, sincronizar_cartera

    def _run() -> None:
        resumen = sincronizar_cartera(dry_run=False)
        emitidos = emitir_avisos_de_fin()
        log.info(
            "cartera_avisos_done",
            ganadas=resumen.ganadas,
            nuevos=resumen.nuevos,
            actualizados=resumen.actualizados,
            sin_fecha=resumen.sin_fecha,
            avisos=emitidos,
        )

    return _run_periodic("cartera_avisos", _SEGUNDOS_DIA, _run)


def _run_documentacion_avisos() -> str:
    """Caducidad de la documentación acreditativa: avisa una vez al día.

    Escribe en el outbox un ``organizacion.documento_caduca`` por documento del
    perfil de capacidad que cruza un umbral (60, 30, 7 días, o caducado), una
    vez por umbral y documento. Va antes de ``event_dispatch`` para que el
    aviso salga en esta misma pasada; el reparto lo hace el despachador, como
    el de cualquier otro evento.
    """
    from services import documentacion_caducidad

    def _run() -> None:
        emitidos = documentacion_caducidad.emitir_avisos_de_caducidad()
        log.info("documentacion_avisos_done", avisos=emitidos)

    return _run_periodic("documentacion_avisos", _SEGUNDOS_DIA, _run)


def _run_follows_paridad() -> str:
    """Paridad `follows` ↔ tablas de origen (ADR-031 §B), una vez al día.

    Diaria y no cada cuatro horas: compara tres tablas enteras y el número no
    se mueve en horas. Lo que interesa es la serie —«lleva N días en cero»—,
    no el instante.
    """
    from scheduler.jobs.follows_paridad import run as run_follows_paridad

    return _run_periodic("follows_paridad", _SEGUNDOS_DIA, run_follows_paridad)


def _run_llm_models_canary() -> str:
    """Canary del catálogo NIM (una vez al día): avisa ANTES del próximo EOL.

    Un modelo ofertado que desaparece del catálogo tumbó la IA seis días en
    silencio (deepseek-v4-pro, 410 sin aviso), y uno que sigue listado pero ya
    no se sirve (404 en el chat, 2026-10-20) también: el canary comprueba las
    dos cosas. Modelos ausentes o sin servir se lanzan como
    fallo del paso: así llega el email de ``_notify_step_failure`` en vez de
    quedarse en un log de runner efímero — que es exactamente donde se ocultó
    el incidente original. Un fallo de red del propio canary NO lanza (el
    job lo reporta como ``error`` y reintenta en la siguiente ventana).
    """

    def _check() -> None:
        from scheduler.jobs.llm_models_canary import run as run_canary

        result = run_canary()
        if result["missing"]:
            raise RuntimeError(
                "Modelos NIM ofertados que ya no se pueden usar: "
                f"{result['missing']} (sin servir, con el chat en 404/410: "
                f"{result['unserved']})"
            )

    return _run_periodic("llm_models_canary", _SEGUNDOS_DIA, _check)


def _run_model_artifacts_canary() -> str:
    """Canary de artefactos de modelo (una vez al día): registro frente a Release.

    Una versión activa en ``model_versions`` cuyo artefacto publicado tiene
    otro sha256 —o no está publicado— no la puede servir ningún proceso. El
    2026-09-29 eso dejó ``ml_scoring`` cayendo cuatro días por
    ``ModelArtifactMismatch``. Los hallazgos se lanzan como fallo del paso por
    el mismo motivo que en ``_run_llm_models_canary``: así llega el email de
    ``_notify_step_failure`` con los dos hashes y la Release, en vez de
    quedarse en el log de un runner efímero. Un fallo leyendo las Releases NO
    lanza: el job lo reporta como ``error`` y la ventana siguiente reintenta.
    """

    def _check() -> None:
        from scheduler.jobs.model_artifacts_canary import resumen
        from scheduler.jobs.model_artifacts_canary import run as run_canary

        result = run_canary()
        hallazgos = resumen(result)
        if hallazgos:
            raise RuntimeError(
                f"model_versions y las Releases divergen: {hallazgos}. Ningún proceso "
                "puede servir esas versiones (docs/runbooks/model-rollback.md)."
            )

    return _run_periodic("model_artifacts_canary", _SEGUNDOS_DIA, _check)
