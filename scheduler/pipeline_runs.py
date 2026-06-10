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
        RuntimeError: Si la ingesta falla (status != "ok").
    """
    from scraper.pipeline import update_daily

    result = update_daily()
    if result.get("status") != "ok":
        raise RuntimeError(f"daily ingestion failed: {result.get('status')}")

    step_results = _run_post_ingestion_steps()

    return {
        "status": "ok",
        "ingestion_result": result,
        "steps": step_results,
    }


def run_bulk_pipeline(months: int = 3) -> dict[str, Any]:
    """Pipeline canónica para el carril bulk (últimos N meses).

    Ejecuta la ingesta bulk y todos los pasos post-ingesta en la secuencia
    oficial. Usada tanto por ``run_update.py --months`` como por
    ``scheduler/jobs/recent_bulk.py``.

    Args:
        months: Número de meses recientes a refrescar.

    Returns:
        Dict con ``ingestion_results``, ``steps`` y ``status``.

    Raises:
        RuntimeError: Si algún mes de la ingesta falla.
    """
    from scraper.pipeline import update_recent

    results = update_recent(months)
    failed = [r for r in results if r.get("status") not in ("ok", "no_publicado")]
    if failed:
        raise RuntimeError(f"bulk refresh failed for {len(failed)} month(s): {failed}")

    step_results = _run_post_ingestion_steps()

    return {
        "status": "ok",
        "ingestion_results": results,
        "steps": step_results,
    }


def run_backfill_pipeline(year: int, month: int) -> dict[str, Any]:
    """Pipeline canónica para backfill histórico (desde año/mes hasta hoy).

    Args:
        year: Año de inicio del backfill.
        month: Mes de inicio del backfill.

    Returns:
        Dict con ``ingestion_results``, ``steps`` y ``status``.

    Raises:
        RuntimeError: Si algún mes de la ingesta falla.
    """
    from scraper.pipeline import backfill

    results = backfill(year, month)
    failed = [r for r in results if r.get("status") not in ("ok", "no_publicado")]
    if failed:
        raise RuntimeError(f"backfill failed for {len(failed)} month(s): {failed}")

    step_results = _run_post_ingestion_steps()

    return {
        "status": "ok",
        "ingestion_results": results,
        "steps": step_results,
    }
