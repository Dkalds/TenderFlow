"""Daily ATOM ingestion + downstream ML scoring, KPI precomputation, and alerts."""

from __future__ import annotations

from observability.logging import get_logger

log = get_logger(__name__)


def run() -> None:
    """Execute the daily ATOM pipeline and all dependent downstream jobs."""
    from scheduler.aggregates_precompute import run_aggregates_precompute
    from scheduler.anomaly_alerts import run_anomaly_checks
    from scheduler.dlq_retry import retry_failed_extractions
    from scheduler.kpi_precompute import run_kpi_precompute
    from scheduler.watchlist_alerts import check_and_notify
    from scraper.pipeline import update_daily

    result = update_daily()
    if result.get("status") != "ok":
        raise RuntimeError(f"daily atom failed: {result.get('status')}")

    # Score new keyword-route licitaciones (ml_proba IS NULL).
    # ML-route entries already have ml_proba set from _ml_classify_entry.
    try:
        from scraper.ml_training import precompute_ml_proba

        precompute_ml_proba(force=False)
    except Exception:
        log.debug("daily_precompute_ml_proba_failed")

    # Multi-technology scoring (feature-flagged). Populates ml_tecnologias,
    # ml_proba_max and the licitacion_tecnologia_score table. No-op when
    # ML_TECH_ENABLED=False or TechnologyClassifier is absent on disk.
    try:
        from config import settings as _settings

        if getattr(_settings, "ML_TECH_ENABLED", False):
            from scraper.ml_training import precompute_ml_tecnologias

            precompute_ml_tecnologias(force=False)
    except Exception:
        log.debug("daily_precompute_ml_tecnologias_failed")

    run_kpi_precompute()
    run_aggregates_precompute()
    check_and_notify()
    retry_failed_extractions()
    run_anomaly_checks()
