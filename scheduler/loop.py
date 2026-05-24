"""Long-running scheduler for Docker Compose deployments.

GitHub Actions remains the preferred production scheduler for Turso-backed
deployments. This loop is for local/self-hosted Docker stacks where Compose
should keep one service alive and run periodic jobs against the shared DB.
"""

from __future__ import annotations

import concurrent.futures
import os
import signal
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from observability import AlertLevel, configure_logging, configure_tracing, get_logger, notify
from scheduler.aggregates_precompute import run_aggregates_precompute
from scheduler.anomaly_alerts import run_anomaly_checks
from scheduler.dlq_retry import retry_failed_extractions
from scheduler.drift_report import run_drift_report
from scheduler.kpi_precompute import run_kpi_precompute
from scheduler.watchlist_alerts import check_and_notify, send_pending_digests
from scraper.pipeline import update_daily, update_recent

log = get_logger(__name__)

# Evento global para shutdown graceful (se activa con SIGTERM/SIGINT)
_stop_event = threading.Event()

# Registro de threads activos por nombre de job para evitar solapamiento (jobs ligeros)
_active_jobs: dict[str, threading.Thread] = {}

# Registro de futures activos por nombre de job para jobs pesados (ProcessPoolExecutor)
_active_heavy_futures: dict[str, concurrent.futures.Future[Any]] = {}

# Registro de fallos consecutivos por job para backoff exponencial
_consecutive_failures: dict[str, int] = {}
_MAX_BACKOFF_MULTIPLIER = 8  # máximo 8x el intervalo original

# Jobs que se ejecutan en proceso separado (cancellables en timeout)
_HEAVY_JOBS = frozenset({"daily_atom", "recent_bulk", "retention_cleanup", "faiss_rebuild"})


def _env_int(name: str, default: int, *, min_value: int = 1) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        log.warning("scheduler_loop_invalid_int", name=name, value=raw, default=default)
        return default
    return max(value, min_value)


def _run_heavy_job(name: str, fn: Callable[[], Any]) -> bool:
    """Ejecuta un job pesado en un proceso separado (cancellable en timeout).

    A diferencia de threads, los procesos pueden terminarse al exceder el
    timeout, evitando zombie workers que consumen recursos indefinidamente.
    """
    from observability.runtime_metrics import scheduler_job_duration_seconds, scheduler_job_total

    # Evitar solapamiento: si el future anterior sigue activo, saltar
    prev_future = _active_heavy_futures.get(name)
    if prev_future is not None and not prev_future.done():
        log.warning("scheduler_loop_job_skipped_overlap", job=name)
        scheduler_job_total.labels(job=name, status="skipped").inc()
        return False

    timeout_s = _env_int("SCHEDULER_JOB_TIMEOUT_SECONDS", 600, min_value=30)
    started = time.monotonic()

    executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)
    future = executor.submit(fn)
    _active_heavy_futures[name] = future

    try:
        future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        log.error(
            "scheduler_loop_job_timeout", job=name, timeout_s=timeout_s, elapsed_ms=elapsed_ms
        )
        notify(AlertLevel.ERROR, f"Scheduler job timeout: {name}", body=f"Excedió {timeout_s}s")
        future.cancel()
        # Forzar terminación del proceso subyacente
        try:
            for proc in executor._processes.values():  # type: ignore[attr-defined]
                proc.kill()
        except Exception:
            pass
        _consecutive_failures[name] = _consecutive_failures.get(name, 0) + 1
        scheduler_job_total.labels(job=name, status="timeout").inc()
        scheduler_job_duration_seconds.labels(job=name).observe(time.monotonic() - started)
        return False
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _consecutive_failures[name] = _consecutive_failures.get(name, 0) + 1
        failures = _consecutive_failures[name]
        log.error(
            "scheduler_loop_job_failed",
            job=name,
            consecutive_failures=failures,
            error=str(exc),
            elapsed_ms=elapsed_ms,
        )
        notify(AlertLevel.ERROR, f"Scheduler job fallo: {name}", body=str(exc))
        scheduler_job_total.labels(job=name, status="error").inc()
        scheduler_job_duration_seconds.labels(job=name).observe(time.monotonic() - started)
        return False
    finally:
        executor.shutdown(wait=False)

    elapsed_s = time.monotonic() - started
    _consecutive_failures.pop(name, None)
    log.info("scheduler_loop_job_done", job=name, elapsed_ms=int(elapsed_s * 1000))
    scheduler_job_total.labels(job=name, status="success").inc()
    scheduler_job_duration_seconds.labels(job=name).observe(elapsed_s)
    return True


def _run_job(name: str, fn: Callable[[], Any]) -> bool:
    """Ejecuta un job ligero en un thread con timeout. Devuelve True si tuvo éxito.

    Para jobs pesados (daily_atom, recent_bulk, retention_cleanup, faiss_rebuild)
    usa ``_run_heavy_job`` que emplea un proceso separado cancellable en timeout.

    Trackea fallos consecutivos por nombre de job para permitir backoff exponencial
    en el loop principal.
    """
    if name in _HEAVY_JOBS:
        return _run_heavy_job(name, fn)

    # Jobs ligeros: thread daemon con join(timeout)
    # Evitar solapamiento: si el job anterior sigue vivo, saltar esta ejecución
    prev = _active_jobs.get(name)
    if prev is not None and prev.is_alive():
        log.warning("scheduler_loop_job_skipped_overlap", job=name)
        return False

    timeout_s = _env_int("SCHEDULER_JOB_TIMEOUT_SECONDS", 600, min_value=30)
    started = time.monotonic()
    result_holder: list[Any] = []
    exc_holder: list[BaseException] = []

    def _target() -> None:
        try:
            result_holder.append(fn())
        except Exception as exc:
            exc_holder.append(exc)

    t = threading.Thread(target=_target, daemon=True)
    _active_jobs[name] = t
    t.start()
    t.join(timeout=timeout_s)

    from observability.runtime_metrics import scheduler_job_duration_seconds, scheduler_job_total

    elapsed_s = time.monotonic() - started
    elapsed_ms = int(elapsed_s * 1000)
    if t.is_alive():
        log.error(
            "scheduler_loop_job_timeout", job=name, timeout_s=timeout_s, elapsed_ms=elapsed_ms
        )
        notify(AlertLevel.ERROR, f"Scheduler job timeout: {name}", body=f"Excedió {timeout_s}s")
        _consecutive_failures[name] = _consecutive_failures.get(name, 0) + 1
        scheduler_job_total.labels(job=name, status="timeout").inc()
        scheduler_job_duration_seconds.labels(job=name).observe(elapsed_s)
        return False
    if exc_holder:
        _consecutive_failures[name] = _consecutive_failures.get(name, 0) + 1
        failures = _consecutive_failures[name]
        log.exception(
            "scheduler_loop_job_failed",
            job=name,
            consecutive_failures=failures,
        )
        notify(AlertLevel.ERROR, f"Scheduler job fallo: {name}", body=str(exc_holder[0]))
        scheduler_job_total.labels(job=name, status="error").inc()
        scheduler_job_duration_seconds.labels(job=name).observe(elapsed_s)
        return False
    # Éxito — resetear contador de fallos
    _consecutive_failures.pop(name, None)
    log.info(
        "scheduler_loop_job_done",
        job=name,
        elapsed_ms=elapsed_ms,
        result=result_holder[0] if result_holder else None,
    )
    scheduler_job_total.labels(job=name, status="success").inc()
    scheduler_job_duration_seconds.labels(job=name).observe(elapsed_s)
    return True


def _backoff_interval(name: str, base_interval: timedelta) -> timedelta:
    """Calcula intervalo con backoff exponencial basado en fallos consecutivos.

    Tras N fallos consecutivos, el próximo intento se demora min(2^N, MAX) * base.
    Esto evita que un job permanentemente roto spamee alertas en cada ciclo.
    """
    failures = _consecutive_failures.get(name, 0)
    if failures == 0:
        return base_interval
    multiplier = min(2**failures, _MAX_BACKOFF_MULTIPLIER)
    backed_off = base_interval * multiplier
    log.info(
        "scheduler_loop_backoff",
        job=name,
        failures=failures,
        multiplier=multiplier,
        next_attempt_minutes=int(backed_off.total_seconds() // 60),
    )
    return backed_off


def _run_daily_atom() -> None:
    result = update_daily()
    if result.get("status") != "ok":
        raise RuntimeError(f"daily atom failed: {result.get('status')}")
    # Puntuar con ML las licitaciones nuevas por ruta keyword (ml_proba IS NULL)
    # Las de ruta ML ya tienen ml_proba seteado desde _ml_classify_entry.
    try:
        from scraper.ml_training import precompute_ml_proba

        precompute_ml_proba(force=False)
    except Exception:
        log.debug("daily_precompute_ml_proba_failed")
    # Multi-tecnología (feature-flagged): pobla ml_tecnologias/ml_proba_max
    # y la tabla licitacion_tecnologia_score. No-op si ML_TECH_ENABLED=False
    # o si TechnologyClassifier no está disponible en disco.
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


def _run_recent_bulk(months: int) -> None:
    results = update_recent(months)
    failed = [r for r in results if r.get("status") not in ("ok", "no_publicado")]
    if failed:
        raise RuntimeError(f"bulk refresh failed for {len(failed)} month(s): {failed}")
    run_kpi_precompute()
    run_aggregates_precompute()
    check_and_notify()


def _run_retention_cleanup() -> dict[str, int]:
    """Purga datos históricos según la política de retención."""
    from scheduler.retention import run_retention

    return run_retention(
        runs_days=90,
        audit_days=180,
        dlq_days=30,
        history_days=365,
        access_days=180,
        idempotency_days=1,
        webhook_deliveries_days=90,
        apply=True,
    )


def _run_recent_bulk_default() -> None:
    """Wrapper top-level para ProcessPoolExecutor — lee bulk_months del entorno."""
    months = _env_int("SCHEDULER_BULK_MONTHS", 3)
    _run_recent_bulk(months)


def _run_wal_checkpoint() -> dict[str, Any]:
    """Ejecuta PRAGMA wal_checkpoint(TRUNCATE) para liberar espacio del WAL."""
    from db.database import connect

    with connect() as c:
        row = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    result = {"blocked": row[0], "wal_pages": row[1], "checkpointed": row[2]} if row else {}
    return result


def _rebuild_faiss_if_stale() -> None:
    """Reconstruye el índice FAISS si los datos han cambiado desde la última build.

    Comprueba si el centinela ``.cache_invalidation`` es más reciente que el
    índice FAISS. Si es así, reconstruye el índice usando los datos actuales
    de la BD. No hace nada si FAISS no está disponible.
    """
    try:
        from dashboard.faiss_index import _INDEX_PATH, _is_index_stale

        if not _INDEX_PATH.exists() or _is_index_stale(_INDEX_PATH):
            from scheduler.queue import enqueue_rebuild_embeddings

            enqueue_rebuild_embeddings()
            log.info("scheduler_faiss_rebuild_triggered")
        else:
            log.debug("scheduler_faiss_index_up_to_date")
    except Exception as exc:
        log.warning("scheduler_faiss_rebuild_failed", error=str(exc))


def main() -> int:
    configure_logging(json_logs=os.environ.get("LOG_FORMAT") == "json")
    configure_tracing()

    # Registrar handlers para shutdown graceful (SIGTERM de Docker, SIGINT de Ctrl+C)
    def _handle_signal(signum: int, frame: object) -> None:
        log.info("scheduler_loop_shutdown_signal", signal=signum)
        _stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    daily_interval = timedelta(minutes=_env_int("SCHEDULER_DAILY_INTERVAL_MINUTES", 240))
    bulk_interval = timedelta(minutes=_env_int("SCHEDULER_BULK_INTERVAL_MINUTES", 1440))
    bulk_months = _env_int("SCHEDULER_BULK_MONTHS", 3)
    dlq_interval = timedelta(minutes=_env_int("SCHEDULER_DLQ_RETRY_INTERVAL_MINUTES", 720))
    digest_interval = timedelta(minutes=_env_int("SCHEDULER_DIGEST_INTERVAL_MINUTES", 1440))
    anomaly_interval = timedelta(minutes=_env_int("SCHEDULER_ANOMALY_INTERVAL_MINUTES", 1440))
    drift_interval = timedelta(
        minutes=_env_int("SCHEDULER_DRIFT_INTERVAL_MINUTES", 10080)
    )  # weekly
    retention_interval = timedelta(hours=_env_int("SCHEDULER_RETENTION_INTERVAL_HOURS", 24))
    wal_interval = timedelta(hours=_env_int("SCHEDULER_WAL_CHECKPOINT_INTERVAL_HOURS", 6))
    faiss_interval = timedelta(minutes=_env_int("SCHEDULER_FAISS_REBUILD_INTERVAL_MINUTES", 60))
    sleep_seconds = _env_int("SCHEDULER_POLL_SECONDS", 60)

    now = datetime.now(UTC)
    next_daily = now
    next_bulk = now
    next_dlq = now + timedelta(minutes=30)
    next_digest = now + timedelta(hours=1)
    next_anomaly = now + timedelta(hours=2)
    next_drift = now + timedelta(hours=6)  # primer drift report: 6h tras arranque
    next_retention = now + timedelta(hours=3)  # primer cleanup: 3h tras arranque
    next_wal = now + timedelta(hours=1)  # primer WAL checkpoint: 1h tras arranque
    next_faiss = now + timedelta(minutes=5)  # primer check FAISS: 5 min tras arranque
    log.info(
        "scheduler_loop_start",
        daily_interval_minutes=int(daily_interval.total_seconds() // 60),
        bulk_interval_minutes=int(bulk_interval.total_seconds() // 60),
        dlq_retry_interval_minutes=int(dlq_interval.total_seconds() // 60),
        digest_interval_minutes=int(digest_interval.total_seconds() // 60),
        anomaly_interval_minutes=int(anomaly_interval.total_seconds() // 60),
        drift_interval_minutes=int(drift_interval.total_seconds() // 60),
        retention_interval_hours=int(retention_interval.total_seconds() // 3600),
        faiss_rebuild_interval_minutes=int(faiss_interval.total_seconds() // 60),
        bulk_months=bulk_months,
    )

    while True:
        now = datetime.now(UTC)
        if now >= next_daily:
            _run_job("daily_atom", _run_daily_atom)
            next_daily = now + _backoff_interval("daily_atom", daily_interval)
        if now >= next_bulk:
            _run_job("recent_bulk", _run_recent_bulk_default)
            next_bulk = now + _backoff_interval("recent_bulk", bulk_interval)
        if now >= next_dlq:
            _run_job("dlq_retry", retry_failed_extractions)
            next_dlq = now + _backoff_interval("dlq_retry", dlq_interval)
        if now >= next_digest:
            _run_job("digest_daily", lambda: send_pending_digests("daily"))
            next_digest = now + _backoff_interval("digest_daily", digest_interval)
        if now >= next_anomaly:
            _run_job("anomaly_checks", run_anomaly_checks)
            next_anomaly = now + _backoff_interval("anomaly_checks", anomaly_interval)
        if now >= next_drift:
            _run_job("drift_report", run_drift_report)
            next_drift = now + _backoff_interval("drift_report", drift_interval)
        if now >= next_retention:
            _run_job("retention_cleanup", _run_retention_cleanup)
            next_retention = now + _backoff_interval("retention_cleanup", retention_interval)
        if now >= next_wal:
            _run_job("wal_checkpoint", _run_wal_checkpoint)
            next_wal = now + _backoff_interval("wal_checkpoint", wal_interval)
        if now >= next_faiss:
            _run_job("faiss_rebuild", _rebuild_faiss_if_stale)
            next_faiss = now + _backoff_interval("faiss_rebuild", faiss_interval)
        # Esperar el poll interval o despertar inmediatamente si llega señal de parada
        if _stop_event.wait(timeout=sleep_seconds):
            log.info("scheduler_loop_stopped_gracefully")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
