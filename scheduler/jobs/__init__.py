"""Scheduler job registry — declarative definition of all periodic jobs.

Usage::

    from scheduler.jobs import ScheduledJob, build_default_registry

    registry = build_default_registry()
    for job in registry:
        print(job.name, job.heavy)
"""

from __future__ import annotations

from scheduler.jobs._base import ScheduledJob

__all__ = ["ScheduledJob", "build_default_registry"]


def build_default_registry() -> list[ScheduledJob]:
    """Return the ordered list of all scheduled jobs with their defaults.

    The order determines evaluation priority when multiple jobs are due in
    the same scheduler cycle.  Heavy jobs run first to maximize pipeline
    throughput; lightweight housekeeping jobs follow.

    Imports are deferred to avoid pulling in heavy dependencies (scraper,
    ML, dashboard) at module load time.
    """
    from scheduler.anomaly_alerts import run_anomaly_checks
    from scheduler.dlq_retry import retry_failed_extractions
    from scheduler.drift_report import run_drift_report
    from scheduler.jobs.daily_atom import run as run_daily_atom
    from scheduler.jobs.documentos_embeddings import run as run_documentos_embeddings
    from scheduler.jobs.llm_tech_labeling import run as run_llm_tech_labeling
    from scheduler.jobs.ml_predicciones import run_retrain as run_ml_retrain
    from scheduler.jobs.ml_predicciones import run_scoring as run_ml_scoring
    from scheduler.jobs.recent_bulk import run as run_recent_bulk
    from scheduler.jobs.retention_cleanup import run as run_retention_cleanup
    from scheduler.jobs.watchlist_rules import run as run_watchlist_rules
    from scheduler.watchlist_alerts import send_pending_digests

    return [
        # ── Heavy jobs (ProcessPoolExecutor) ──────────────────────────
        ScheduledJob(
            name="daily_atom",
            plane="actions",
            module="scheduler.run_update",
            fn=run_daily_atom,
            interval_env="SCHEDULER_DAILY_INTERVAL_MINUTES",
            default_interval_minutes=240,
            initial_offset_minutes=0,
            heavy=True,
        ),
        ScheduledJob(
            # plane='manual' (2026-08): el refresh de N meses ya no tiene cron.
            # El carril ATOM de daily_atom trae las novedades cada 4h, así que
            # a diario el bulk sólo reprocesaba meses ya ingeridos y competía
            # por la ventana del job diario. Vive en el workflow
            # `.github/workflows/scrape-bulk.yml`, workflow_dispatch-only.
            # `default_interval_minutes` sigue definiendo la cadencia del plano
            # APScheduler (docker-compose), que no es el plano activo.
            name="recent_bulk",
            plane="manual",
            module="scheduler.run_update",
            fn=run_recent_bulk,
            interval_env="SCHEDULER_BULK_INTERVAL_MINUTES",
            default_interval_minutes=1440,
            initial_offset_minutes=0,
            heavy=True,
        ),
        ScheduledJob(
            name="retention_cleanup",
            plane="pipeline",
            fn=run_retention_cleanup,
            interval_env="SCHEDULER_RETENTION_INTERVAL_HOURS",
            default_interval_minutes=1440,  # 24h
            initial_offset_minutes=180,  # 3h after start
            heavy=True,
        ),
        ScheduledJob(
            name="ml_scoring_baja",
            plane="actions",
            module="scheduler.jobs.ml_predicciones",
            fn=run_ml_scoring,
            interval_env="SCHEDULER_ML_SCORING_INTERVAL_MINUTES",
            default_interval_minutes=1440,  # nocturno
            initial_offset_minutes=240,  # tras la ingesta diaria
            heavy=True,  # construye el dataset histórico completo
        ),
        ScheduledJob(
            name="ml_retrain_baja",
            plane="pipeline",
            fn=run_ml_retrain,
            interval_env="SCHEDULER_ML_RETRAIN_INTERVAL_MINUTES",
            default_interval_minutes=43_200,  # mensual
            initial_offset_minutes=720,
            heavy=True,
        ),
        ScheduledJob(
            name="documentos_embeddings",
            plane="actions",
            module="scheduler.jobs.documentos_embeddings",
            fn=run_documentos_embeddings,
            interval_env="SCHEDULER_DOCUMENTOS_EMBEDDINGS_INTERVAL_MINUTES",
            default_interval_minutes=1440,  # nocturno
            initial_offset_minutes=300,  # tras la ingesta diaria + scoring
            heavy=True,  # descarga de red + inferencia del modelo de embeddings
        ),
        # ── Light jobs (daemon threads) ───────────────────────────────
        ScheduledJob(
            name="dlq_retry",
            plane="pipeline",
            fn=retry_failed_extractions,
            interval_env="SCHEDULER_DLQ_RETRY_INTERVAL_MINUTES",
            default_interval_minutes=720,
            initial_offset_minutes=30,
        ),
        ScheduledJob(
            name="digest_daily",
            plane="pipeline",
            fn=lambda: send_pending_digests("daily"),
            interval_env="SCHEDULER_DIGEST_INTERVAL_MINUTES",
            default_interval_minutes=1440,
            initial_offset_minutes=60,
        ),
        ScheduledJob(
            name="watchlist_rules",
            plane="pipeline",
            fn=run_watchlist_rules,
            interval_env="SCHEDULER_WATCHLIST_RULES_INTERVAL_MINUTES",
            default_interval_minutes=240,  # mismo cadencia que daily_atom
            initial_offset_minutes=15,
        ),
        ScheduledJob(
            # Ligero pese a llamar al LLM: es I/O de red secuencial, no CPU, así
            # que no justifica el ProcessPoolExecutor de los jobs heavy. La
            # cadencia real la impone `_run_periodic` (diaria) dentro del paso
            # canónico; este intervalo gobierna el plano APScheduler.
            name="llm_tech_labeling",
            plane="pipeline",
            fn=run_llm_tech_labeling,
            interval_env="SCHEDULER_LLM_TECH_LABELING_INTERVAL_MINUTES",
            default_interval_minutes=1440,
            initial_offset_minutes=300,
        ),
        ScheduledJob(
            name="anomaly_checks",
            plane="pipeline",
            fn=run_anomaly_checks,
            interval_env="SCHEDULER_ANOMALY_INTERVAL_MINUTES",
            default_interval_minutes=1440,
            initial_offset_minutes=120,
        ),
        ScheduledJob(
            name="drift_report",
            plane="pipeline",
            fn=run_drift_report,
            interval_env="SCHEDULER_DRIFT_INTERVAL_MINUTES",
            default_interval_minutes=10080,  # weekly
            initial_offset_minutes=360,  # 6h after start
        ),
    ]
