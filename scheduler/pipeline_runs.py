"""Pipeline canónica de orquestación — ADR-012.

Define la secuencia oficial de pasos post-ingesta. Tanto ``run_update.py``
(GitHub Actions) como ``loop.py`` / ``jobs/`` (APScheduler Docker) **delegan**
en estas funciones para garantizar paridad.

Secuencia canónica::

    ingesta → ML scoring → analytics export → KPI precompute
            → aggregates precompute → watchlist notify → digests
            → DLQ retry → anomaly checks → retention cleanup
            → ML retrain → drift checks

``tech_signal_merge`` corre justo después de ``ml_tecnologias``: re-aplica la
señal de tecnología detectada en los pliegos (``services/tech_signal.py``)
sobre ``ml_tecnologias``/``licitacion_tecnologia_score``, sanando el clobber
que ``precompute_ml_tecnologias`` acaba de hacer sobre esas mismas columnas
(``db/upsert.py`` también las resetea en cada re-scrape -- ver docstring de
``_run_tech_signal_merge``).

``digests``, ``retention_cleanup`` y ``drift_checks`` tienen **cadencia
propia** (ver ``_run_periodic``): la pipeline corre cada 4h, pero un digest
diario debe enviarse una vez al día y la retención purgar una vez al día,
no seis.
"""

from __future__ import annotations

from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Pasos individuales (best-effort wrappers)
# ---------------------------------------------------------------------------

# Los pasos que no deben abortar la pipeline capturan excepciones y loguean.
# El orden de esta lista define el contrato de la secuencia canónica.

CANONICAL_STEPS: list[str] = [
    "ml_scoring",
    "ml_tecnologias",
    "tech_signal_merge",
    "llm_tech_labeling",
    "analytics_export",
    "kpi_precompute",
    "aggregates_precompute",
    "watchlist_notify",
    "digests",
    "dlq_retry",
    "anomaly_checks",
    "retention_cleanup",
    "sap_active_learning",
    "drift_checks",
]

# `ml_retrain` salió de la lista en 2026-08: vive en
# `.github/workflows/train-predictivos.yml`. Entrenaba aquí, dentro de un job
# con `permissions: contents: read`, así que el artefacto no podía publicarse
# en la Release y moría con el runner efímero — dejando filas de
# `model_versions` con un `path` que ningún job posterior podía resolver. El
# workflow nuevo entrena Y publica; duplicarlo aquí volvería a registrar
# versiones irresolubles.


# ---------------------------------------------------------------------------
# Carriles
# ---------------------------------------------------------------------------

# El carril diario corre cada 4h dentro de un job de 55 min; el bulk se dispara
# a mano (`.github/workflows/scrape-bulk.yml`) con 120 min. Un mismo paso
# canónico puede por tanto permitirse más trabajo en un carril que en el otro:
# los pasos listados en ``_LANE_AWARE_STEPS`` reciben ``lane=`` y deciden.
LANE_DAILY = "daily"
LANE_BULK = "bulk"

_LANE_AWARE_STEPS = frozenset({"dlq_retry"})


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


def _run_ml_scoring() -> None:
    """Score keyword-route licitaciones (ml_proba IS NULL).

    Sin try/except propio: hasta 2026-08 tragaba cualquier excepción a nivel
    debug y reportaba "ok" al ejecutor, así que un scoring roto era invisible.
    El ejecutor canónico ya aísla y alerta los fallos de cada paso.
    """
    from scraper.ml_training import precompute_ml_proba

    precompute_ml_proba(force=False)


def _run_ml_tecnologias() -> None:
    """Multi-technology scoring (feature-flagged).

    Sin try/except propio por el mismo motivo que ``_run_ml_scoring``.
    """
    from config import settings as _settings

    if getattr(_settings, "ML_TECH_ENABLED", False):
        from scraper.ml_training import precompute_ml_tecnologias

        precompute_ml_tecnologias(force=False)


def _run_tech_signal_merge() -> None:
    """Re-aplica la señal de pliego sobre TODAS las licitaciones con señal.

    ``precompute_ml_tecnologias`` (paso anterior) sobreescribe
    ``ml_tecnologias``/``ml_proba_max``/``ml_tech_principal`` para toda fila
    con ``ml_proba_max IS NULL`` -- lo mismo que ``db/upsert.py`` hace en cada
    re-scrape (ver docstring de ``_LIC_UPDATES``). Sin este paso, un merge ya
    aplicado revertiría a la señal de solo-título en la primera re-ingesta o
    el primer precompute posterior. Barato (≤ ~11k licitaciones con pliegos
    procesados) y fail-open por licitación -- no hace falta ``try/except``
    aquí porque ``merge_doc_signals`` ya captura y cuenta los fallos.
    """
    from services.tech_signal import merge_doc_signals

    merge_doc_signals()


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
    """
    from scheduler.jobs.llm_tech_labeling import batch_failed_systemically
    from scheduler.jobs.llm_tech_labeling import run as run_llm_tech_labeling

    def _run_and_check() -> None:
        counts = run_llm_tech_labeling()
        if batch_failed_systemically(counts):
            raise RuntimeError(f"El lote de etiquetado por LLM falló entero: {counts}")

    return _run_periodic("llm_tech_labeling", _SEGUNDOS_DIA, _run_and_check)


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
        log.warning("pipeline_analytics_export_failed", error=str(exc))


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
        log.warning("competitor_alerts_failed", error=str(e))
    # Alertas de reglas de watchlist por criterio (mi-watchlist, v43)
    try:
        from scheduler.watchlist_rules_alerts import check_rules_and_notify

        check_rules_and_notify()
    except Exception as e:
        log.warning("watchlist_rules_alerts_failed", error=str(e))


def _run_digests() -> dict[str, str]:
    """Drena ``pending_digests`` para las frecuencias daily y weekly.

    ``_run_watchlist_notify`` (arriba) **acumula** las coincidencias de las
    entradas con ``frequency`` daily/weekly en ``pending_digests``, pero hasta
    ahora nada las vaciaba en producción: ``send_pending_digests`` solo estaba
    registrado en el plano APScheduler, que no es el plano activo (ADR-012).
    El resultado era que quien elegía digest diario o semanal no recibía nunca
    el email. Este paso cierra ese camino.
    """
    from scheduler.watchlist_alerts import send_pending_digests

    return {
        "daily": _run_periodic(
            "digest_daily", _SEGUNDOS_DIA, lambda: send_pending_digests("daily")
        ),
        "weekly": _run_periodic(
            "digest_weekly", _SEGUNDOS_SEMANA, lambda: send_pending_digests("weekly")
        ),
    }


def _run_retention_cleanup() -> str:
    """Purga histórico según la política de retención (una vez al día)."""
    from scheduler.jobs.retention_cleanup import run as run_retention_cleanup

    return _run_periodic("retention_cleanup", _SEGUNDOS_DIA, run_retention_cleanup)


def _run_sap_active_learning() -> str:
    """Active learning del clasificador SAP (una vez por semana).

    ``maybe_retrain_classifier`` (feedback ≥50 → retrain + gate de promoción
    de tres métricas) estaba implementado y testeado pero SIN ningún caller de
    producción: el feedback se acumulaba en ``ml_feedback`` para un contador
    de UI y nada lo consumía (revisión de arquitectura 2026-08). La función ya
    no-opea por debajo del umbral, así que la ventana semanal solo limita el
    coste del conteo. OJO runners efímeros: si promociona una versión nueva,
    el artefacto debe subirse a la Release (canal de ``ensure_downloaded``) —
    la propia función lo avisa en su log de promoción.
    """

    def _run() -> None:
        from scheduler.concept_drift import maybe_retrain_classifier

        result = maybe_retrain_classifier()
        if result.get("triggered") and result.get("new_version") is not None:
            log.warning(
                "sap_active_learning_promoted_artifact_needs_release_upload",
                detail=(
                    "una versión nueva quedó activa en model_versions; subir el "
                    ".pkl a la Release de GitHub o el siguiente runner no podrá "
                    "resolver el artefacto (shared/model_artifacts.py)"
                ),
            )

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

    Una entrada ``bulk_YYYYMM`` se reintenta llamando a ``process_month``: la
    descarga y el reparseo de los ZIP de un mes entero, más su resolución de
    entidades. Con la DLQ arrastrando varios meses, ese trabajo se comía el
    presupuesto entero del job diario y GitHub lo cancelaba a mitad de la
    cadena post-ingesta (runs de 2026-08-01/03: cancelados dentro de
    ``dlq_retry`` reprocesando siete ficheros ``...Completo3_2026MM....atom``).
    El diario deja de tocarlas y las cubre `scrape-bulk.yml`, que es donde
    reprocesar meses tiene sentido y presupuesto.
    """
    from scheduler.dlq_retry import retry_failed_extractions

    retry_failed_extractions(include_bulk=lane != LANE_DAILY)


def _run_anomaly_checks() -> None:
    from scheduler.anomaly_alerts import run_anomaly_checks

    run_anomaly_checks()


# ---------------------------------------------------------------------------
# Funciones canónicas de pipeline
# ---------------------------------------------------------------------------


def _notify_step_failure(step: str, exc: Exception) -> None:
    """Alerta best-effort de un paso canónico fallido.

    Hasta 2026-08 un paso fallido solo dejaba una línea de log en un runner
    efímero de Actions: ningún notify(), ninguna métrica, exit code intacto.
    Así se ocultó semanas el cursor PSCP atascado. El plano APScheduler
    (loop.py) siempre alertó sus fallos; el plano activo no.
    """
    try:
        from observability.alerts import notify

        notify(
            "error",
            f"[pipeline] paso {step} falló",
            body=f"{type(exc).__name__}: {exc}"[:500],
            step=step,
        )
    except Exception:
        log.warning("pipeline_step_alert_failed", step=step)


def _run_post_ingestion_steps(*, lane: str = LANE_BULK) -> dict[str, str]:
    """Ejecuta todos los pasos post-ingesta en orden canónico.

    ``CANONICAL_STEPS`` es la única fuente del orden: las implementaciones se
    resuelven por nombre contra este módulo (mantiene parcheable cada paso en
    tests). Antes existían dos literales — la constante y una lista de tuplas
    aquí — que había que sincronizar a mano y el checker de paridad solo leía
    la constante.

    Args:
        lane: ``LANE_DAILY`` o ``LANE_BULK``. Sólo lo reciben los pasos de
            ``_LANE_AWARE_STEPS``; el resto se ejecuta igual en ambos carriles.
            El default es el carril bulk — el permisivo — para que un caller
            que no lo declare no pierda trabajo en silencio.

    Returns:
        Dict ``{step_name: "ok" | "error"}`` con el resultado de cada paso.
    """
    results: dict[str, str] = {}
    for name in CANONICAL_STEPS:
        fn = globals().get(f"_run_{name}")
        if fn is None:
            raise RuntimeError(
                f"CANONICAL_STEPS contiene '{name}' sin implementación _run_{name} — "
                "la constante y las funciones de paso divergieron"
            )
        try:
            if name in _LANE_AWARE_STEPS:
                fn(lane=lane)
            else:
                fn()
            results[name] = "ok"
        except Exception as exc:
            log.exception("pipeline_step_failed", step=name)
            results[name] = "error"
            _notify_step_failure(name, exc)

    return results


def run_post_ingestion_only(*, lane: str = LANE_DAILY) -> dict[str, Any]:
    """Solo el cierre de la pasada: los pasos post-ingesta, sin ingerir nada.

    Existe para que el workflow pueda ejecutar el cierre **después** de todos
    los conectores y no en medio de ellos.

    ``scrape-daily.yml`` corría ``run_update --daily`` —ingesta PLACSP *más*
    toda la secuencia canónica— y solo entonces lanzaba TED, Galicia, Euskadi,
    adjudicaciones vigiladas, PSCP y TACRC. O sea que el refresco de
    ``licitaciones_canonicas``, los KPIs precalculados y la evaluación de las
    reglas de vigilancia ocurrían antes de que cinco de las siete fuentes
    hubieran ingerido nada: su corpus del ciclo no entraba en la superficie
    pública, ni en los agregados, ni en las alertas hasta cuatro horas después.
    El contrato de ``db/repositories/publico.py`` dice que la vista se refresca
    «al final de la pasada de ingesta»; esta función es lo que hace que sea
    verdad.

    Returns:
        Dict con ``steps`` y ``status`` (``ok`` si ningún paso falló).
    """
    step_results = _run_post_ingestion_steps(lane=lane)
    fallidos = [name for name, estado in step_results.items() if estado != "ok"]
    return {
        "status": "ok" if not fallidos else "degraded",
        "steps": step_results,
    }


def run_daily_pipeline(*, con_cierre: bool = True) -> dict[str, Any]:
    """Pipeline canónica para el carril diario (feed ATOM).

    Ejecuta la ingesta diaria y todos los pasos post-ingesta en la secuencia
    oficial. Usada tanto por ``run_update.py --daily`` como por
    ``scheduler/jobs/daily_atom.py``.

    Args:
        con_cierre: si es ``False`` ingiere y **no** ejecuta los pasos
            post-ingesta, que quedan para una invocación posterior de
            :func:`run_post_ingestion_only`. Lo usa ``scrape-daily.yml`` para
            que el cierre ocurra tras los seis conectores. El default es
            ``True`` para que ningún caller pierda el cierre por omisión.

    Cuando ``PLACSP_CONNECTOR_ENABLED=True`` (F2), usa ``PlacspAtomConnector``
    a través de ``run_connector``; si es False, usa el pipeline legacy.

    Returns:
        Dict con ``ingestion_result``, ``steps`` y ``status``.

    Raises:
        RuntimeError: Solo si la ingesta falla con un status inesperado.
            Los errores ya manejados en ``process_daily`` (``error_fetch``,
            ``error_persistencia``) no relanzarán excepción para evitar
            doble-alerta — las notificaciones ya se enviaron dentro del pipeline.
    """
    from config import settings as _settings

    if getattr(_settings, "PLACSP_CONNECTOR_ENABLED", False):
        return _run_daily_pipeline_connector(con_cierre=con_cierre)

    # ── Legacy path ──────────────────────────────────────────────────────────
    from scraper.pipeline import update_daily

    _HANDLED_STATUSES = frozenset({"error_fetch", "error_persistencia"})

    result = update_daily()
    status = result.get("status", "error")

    if status != "ok" and status not in _HANDLED_STATUSES:
        raise RuntimeError(f"daily ingestion failed: {status}")

    step_results = _run_post_ingestion_steps(lane=LANE_DAILY) if con_cierre else {}

    return {
        "status": status,
        "ingestion_result": result,
        "steps": step_results,
    }


def _run_daily_pipeline_connector(*, con_cierre: bool = True) -> dict[str, Any]:
    """Implementación del carril diario usando PlacspAtomConnector (F2).

    Mantiene paridad operacional con el camino legacy (``update_daily``):

    - ``ingestion_result`` expone ``inserted``/``modified`` como **listas de
      id_externo** (mismo contrato que ``process_daily``; ``_log_daily_summary``
      hace ``len()`` y ``join()`` sobre ellas).
    - Los errores por-entry (parse → DLQ) **no** marcan el run como fallido —
      igual que ``entries_error`` en legacy. Solo un fallo fatal de ``fetch``
      produce ``status="error_fetch"`` (mismo nombre de status que legacy).
    - Escribe ``log_extraccion`` (tabla ``extracciones``, fuente ``placsp``) y
      envuelve el run en ``record_run`` para que la página de observabilidad
      siga viendo los runs diarios tras el flip.
    """
    from db.database import log_extraccion
    from observability import bind_run_context, record_run
    from scraper.connectors.base import run_connector
    from scraper.connectors.placsp import PlacspAtomConnector

    run_id = bind_run_context(entrypoint="run_daily_pipeline_connector")
    with record_run(run_id) as metrics:
        connector = PlacspAtomConnector()
        run_result = run_connector(connector)

        status = "error_fetch" if run_result.fetch_failed else "ok"

        if run_result.fetch_failed:
            metrics.status = "error"
            metrics.months_failed = 1
            try:
                from observability.alerts import AlertLevel, notify

                notify(
                    AlertLevel.ERROR,
                    "Feed diario ATOM falló al descargar (connector)",
                    body="run_connector(placsp) abortó en fetch; detalle en DLQ.",
                )
            except Exception:
                log.debug("daily_connector_notify_failed")
        else:
            metrics.status = "ok"
            metrics.licitaciones_nuevas = run_result.nuevas
            metrics.licitaciones_actualizadas = run_result.actualizadas
        metrics.notas = f"daily_connector|{status}"

        if not run_result.fetch_failed:
            try:
                log_extraccion(
                    fuente=run_result.source_id,
                    nuevas=run_result.nuevas,
                    actualizadas=run_result.actualizadas,
                    total=run_result.parsed,
                    notas=(
                        f"connector matches:{run_result.parsed} "
                        f"adj:{run_result.adjudicaciones} "
                        f"inserted:{run_result.nuevas} modified:{run_result.actualizadas} "
                        f"errors:{run_result.errores}"
                    ),
                )
            except Exception:
                log.warning("daily_connector_log_extraccion_failed")

    step_results = _run_post_ingestion_steps(lane=LANE_DAILY) if con_cierre else {}

    return {
        "status": status,
        "ingestion_result": {
            "status": status,
            "source": run_result.source_id,
            "tech_matches": run_result.parsed,
            "inserted": list(run_result.inserted_ids),
            "modified": list(run_result.modified_ids),
            "unchanged": [],
            "entries_error": run_result.errores,
        },
        "connector_result": run_result.as_dict(),
        "steps": step_results,
    }


_OK_STATUSES = frozenset({"ok", "no_publicado"})


def _notify_degraded(label: str, failed: list[dict[str, Any]]) -> None:
    """Alerta best-effort (nivel WARN) por meses con fallo recuperable."""
    try:
        from observability.alerts import AlertLevel, notify

        notify(
            AlertLevel.WARN,
            f"{label}: {len(failed)} mes(es) con fallo recuperable",
            body=(
                f"Meses fallidos: {failed}. Ya registrados en la DLQ. Los "
                "reintenta el paso post-ingesta dlq_retry del propio carril "
                "bulk, que desde 2026-08 se dispara a mano "
                "(.github/workflows/scrape-bulk.yml): el carril diario ya no "
                "reprocesa meses, así que vuelve a lanzar el bulk si estos "
                "meses importan."
            ),
            failed_months=failed,
        )
    except Exception:
        log.debug("degraded_notify_failed", label=label)


def _finalize_ingestion(results: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    """Cierra una ingesta bulk/backfill tolerando fallos parciales.

    - **Fallo total** (ningún mes ingresó): se lanza ``RuntimeError`` porque no
      hay nada que post-procesar (típicamente PLACSP caído o formato incompatible).
    - **Fallo parcial** (algunos meses fallaron): los fallos ya quedaron
      registrados en la DLQ vía ``record_failure``. Se ejecutan igualmente los
      pasos post-ingesta —incluido ``dlq_retry``, que en este carril sí
      reintenta las descargas mensuales fallidas— y se devuelve
      ``status="degraded"`` en lugar de abortar toda la pipeline. Esto da
      paridad con ``run_daily_pipeline``.
    """
    failed = [r for r in results if r.get("status") not in _OK_STATUSES]
    succeeded = [r for r in results if r.get("status") in _OK_STATUSES]

    # Fallo total: ningún mes ingresó → genuinamente fatal.
    if results and not succeeded:
        raise RuntimeError(f"{label} failed for all {len(failed)} month(s): {failed}")

    if failed:
        log.warning(
            "pipeline_ingestion_degraded",
            label=label,
            failed_months=failed,
            months_ok=len(succeeded),
        )
        _notify_degraded(label, failed)

    step_results = _run_post_ingestion_steps(lane=LANE_BULK)

    return {
        "status": "degraded" if failed else "ok",
        "ingestion_results": results,
        "failed_months": failed,
        "steps": step_results,
    }


def run_bulk_pipeline(months: int = 3) -> dict[str, Any]:
    """Pipeline canónica para el carril bulk (últimos N meses).

    Cuando ``PLACSP_CONNECTOR_ENABLED=True`` (F2), usa ``PlacspBulkConnector``
    a través de ``run_connector``; si es False, usa el pipeline legacy.

    Un fallo transitorio en algún mes reciente **no** aborta la pipeline: se
    registra en la DLQ, se ejecutan los pasos post-ingesta (incluido el
    reintento de la DLQ) y se devuelve ``status="degraded"``. Solo se lanza
    ``RuntimeError`` si fallan todos los meses.

    Args:
        months: Número de meses recientes a refrescar.

    Returns:
        Dict con ``status`` (``ok``/``degraded``), ``ingestion_results``,
        ``failed_months`` y ``steps``.

    Raises:
        RuntimeError: Solo si fallan todos los meses de la ingesta.
    """
    from config import settings as _settings

    if getattr(_settings, "PLACSP_CONNECTOR_ENABLED", False):
        return _run_bulk_pipeline_connector(months)

    from scraper.pipeline import update_recent

    results = update_recent(months)
    return _finalize_ingestion(results, label="bulk refresh")


def run_backfill_pipeline(year: int, month: int) -> dict[str, Any]:
    """Pipeline canónica para backfill histórico (desde año/mes hasta hoy).

    Aplica la misma tolerancia a fallos parciales que ``run_bulk_pipeline``.

    Args:
        year: Año de inicio del backfill.
        month: Mes de inicio del backfill.

    Returns:
        Dict con ``status`` (``ok``/``degraded``), ``ingestion_results``,
        ``failed_months`` y ``steps``.

    Raises:
        RuntimeError: Solo si fallan todos los meses del backfill.
    """
    from scraper.pipeline import backfill

    results = backfill(year, month)
    return _finalize_ingestion(results, label="backfill")


def _run_bulk_pipeline_connector(months: int) -> dict[str, Any]:
    """Implementación del carril bulk usando PlacspBulkConnector (F2).

    Paridad operacional con el camino legacy (``update_recent``):

    - Un fallo fatal de ``fetch`` de un mes se marca ``status="error"`` (los
      errores por-entry van a DLQ y **no** fallan el mes — igual que
      ``entries_error`` en ``process_month``).
    - ``log_extraccion`` por mes con la misma ``fuente`` (``bulk_YYYYMM``) que
      usaba el legacy, para continuidad de la serie en ``extracciones``.
    - El run completo va envuelto en ``record_run`` (observabilidad).
    """
    from datetime import UTC, datetime

    from dateutil.relativedelta import relativedelta

    from db.database import log_extraccion
    from observability import bind_run_context, record_run
    from scraper.connectors.base import run_connector
    from scraper.connectors.placsp import PlacspBulkConnector
    from scraper.pipeline import _summarize

    today = datetime.now(UTC).date()
    month_results: list[dict[str, Any]] = []

    run_id = bind_run_context(entrypoint="run_bulk_pipeline_connector", months=months)
    with record_run(run_id) as metrics:
        for i in range(months):
            target = today - relativedelta(months=i)
            connector = PlacspBulkConnector(target.year, target.month)
            try:
                r = run_connector(connector)
                status = "error" if r.fetch_failed else "ok"
                month_results.append(
                    {
                        "year": target.year,
                        "month": target.month,
                        "status": status,
                        "nuevas": r.nuevas,
                        "actualizadas": r.actualizadas,
                        "adjudicaciones": r.adjudicaciones,
                        "entries_error": r.errores,
                    }
                )
                if not r.fetch_failed:
                    try:
                        log_extraccion(
                            fuente=r.source_id,
                            nuevas=r.nuevas,
                            actualizadas=r.actualizadas,
                            total=r.parsed,
                            notas=(
                                f"connector matches:{r.parsed} adj:{r.adjudicaciones} "
                                f"errors:{r.errores}"
                            ),
                        )
                    except Exception:
                        log.warning(
                            "bulk_connector_log_extraccion_failed",
                            year=target.year,
                            month=target.month,
                        )
            except Exception as exc:
                log.exception(
                    "bulk_connector_month_failed",
                    year=target.year,
                    month=target.month,
                    error=str(exc),
                )
                month_results.append(
                    {
                        "year": target.year,
                        "month": target.month,
                        "status": "error",
                    }
                )
        _summarize(month_results, metrics)

    return _finalize_ingestion(month_results, label="bulk refresh (connector)")
