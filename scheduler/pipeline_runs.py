"""Pipeline canónica de orquestación — ADR-012.

Define la secuencia oficial de pasos post-ingesta. Tanto ``run_update.py``
(GitHub Actions) como ``loop.py`` / ``jobs/`` (APScheduler Docker) **delegan**
en estas funciones para garantizar paridad.

Secuencia canónica::

    ingesta → ML scoring → analytics export → KPI precompute
            → aggregates precompute → watchlist notify → DLQ retry → anomaly checks
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
    "analytics_export",
    "kpi_precompute",
    "aggregates_precompute",
    "watchlist_notify",
    "dlq_retry",
    "anomaly_checks",
]


def _run_ml_scoring() -> None:
    """Score keyword-route licitaciones (ml_proba IS NULL)."""
    try:
        from scraper.ml_training import precompute_ml_proba

        precompute_ml_proba(force=False)
    except Exception:
        log.debug("pipeline_ml_scoring_failed")


def _run_ml_tecnologias() -> None:
    """Multi-technology scoring (feature-flagged)."""
    try:
        from config import settings as _settings

        if getattr(_settings, "ML_TECH_ENABLED", False):
            from scraper.ml_training import precompute_ml_tecnologias

            precompute_ml_tecnologias(force=False)
    except Exception:
        log.debug("pipeline_ml_tecnologias_failed")


def _run_analytics_export() -> None:
    """Snapshot Parquet + manifest de linaje (RFC-086). Best-effort."""
    try:
        from db.analytics import run_analytics_export

        run_analytics_export()
    except Exception:
        log.debug("pipeline_analytics_export_failed")


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
        n_empresas=result.get("n_empresas"),
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


def _run_dlq_retry() -> None:
    from scheduler.dlq_retry import retry_failed_extractions

    retry_failed_extractions()


def _run_anomaly_checks() -> None:
    from scheduler.anomaly_alerts import run_anomaly_checks

    run_anomaly_checks()


# ---------------------------------------------------------------------------
# Funciones canónicas de pipeline
# ---------------------------------------------------------------------------


def _run_post_ingestion_steps() -> dict[str, str]:
    """Ejecuta todos los pasos post-ingesta en orden canónico.

    Returns:
        Dict ``{step_name: "ok" | "error"}`` con el resultado de cada paso.
    """
    steps: list[tuple[str, Any]] = [
        ("ml_scoring", _run_ml_scoring),
        ("ml_tecnologias", _run_ml_tecnologias),
        ("analytics_export", _run_analytics_export),
        ("kpi_precompute", _run_kpi_precompute),
        ("aggregates_precompute", _run_aggregates_precompute),
        ("watchlist_notify", _run_watchlist_notify),
        ("dlq_retry", _run_dlq_retry),
        ("anomaly_checks", _run_anomaly_checks),
    ]

    results: dict[str, str] = {}
    for name, fn in steps:
        try:
            fn()
            results[name] = "ok"
        except Exception:
            log.exception("pipeline_step_failed", step=name)
            results[name] = "error"

    return results


def run_daily_pipeline() -> dict[str, Any]:
    """Pipeline canónica para el carril diario (feed ATOM).

    Ejecuta la ingesta diaria y todos los pasos post-ingesta en la secuencia
    oficial. Usada tanto por ``run_update.py --daily`` como por
    ``scheduler/jobs/daily_atom.py``.

    Returns:
        Dict con ``ingestion_result``, ``steps`` y ``status``.

    Raises:
        RuntimeError: Solo si la ingesta falla con un status inesperado.
            Los errores ya manejados en ``process_daily`` (``error_fetch``,
            ``error_persistencia``) no relanzarán excepción para evitar
            doble-alerta — las notificaciones ya se enviaron dentro del pipeline.
    """
    from scraper.pipeline import update_daily

    # Estos estados ya producen alertas dentro de process_daily; no re-lanzar.
    _HANDLED_STATUSES = frozenset({"error_fetch", "error_persistencia"})

    result = update_daily()
    status = result.get("status", "error")

    if status != "ok" and status not in _HANDLED_STATUSES:
        raise RuntimeError(f"daily ingestion failed: {status}")

    # Los pasos post-ingesta operan sobre la BD existente y deben correr
    # incluso si el fetch falló (evita dejar KPIs y ML desactualizados).
    step_results = _run_post_ingestion_steps()

    return {
        "status": status,
        "ingestion_result": result,
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
                f"Meses fallidos: {failed}. Ya registrados en la DLQ; el paso "
                "post-ingesta dlq_retry los reintentará automáticamente."
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
      pasos post-ingesta —incluido ``dlq_retry``, que reintentará las descargas
      fallidas— y se devuelve ``status="degraded"`` en lugar de abortar toda la
      pipeline. Esto da paridad con ``run_daily_pipeline``.
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

    step_results = _run_post_ingestion_steps()

    return {
        "status": "degraded" if failed else "ok",
        "ingestion_results": results,
        "failed_months": failed,
        "steps": step_results,
    }


def run_bulk_pipeline(months: int = 3) -> dict[str, Any]:
    """Pipeline canónica para el carril bulk (últimos N meses).

    Ejecuta la ingesta bulk y todos los pasos post-ingesta en la secuencia
    oficial. Usada tanto por ``run_update.py --months`` como por
    ``scheduler/jobs/recent_bulk.py``.

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
