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
from typing import Any, cast

from observability import (
    AlertLevel,
    configure_logging,
    configure_sentry,
    configure_tracing,
    get_logger,
    notify,
)
from observability.runtime_metrics import scheduler_job_duration_seconds, scheduler_job_total
from scheduler.jobs import ScheduledJob, build_default_registry

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

# Persistent ProcessPoolExecutor — created once in main(), reused across invocations.
# This avoids the overhead of spawning a new process pool for every heavy job execution.
_heavy_executor: concurrent.futures.ProcessPoolExecutor | None = None


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

    Uses the module-level ``_heavy_executor`` (persistent) instead of creating
    a new ``ProcessPoolExecutor`` per invocation.
    """
    global _heavy_executor

    # Evitar solapamiento: si el future anterior sigue activo, saltar
    prev_future = _active_heavy_futures.get(name)
    if prev_future is not None and not prev_future.done():
        log.warning("scheduler_loop_job_skipped_overlap", job=name)
        scheduler_job_total.labels(job=name, status="skipped").inc()
        return False

    if _heavy_executor is None:
        _heavy_executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)

    timeout_s = _env_int("SCHEDULER_JOB_TIMEOUT_SECONDS", 600, min_value=30)
    started = time.monotonic()

    future = _heavy_executor.submit(fn)
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
        # Terminate the hung worker and recreate the pool. Shutting down with
        # cancel_futures=True is safer than poking at executor._processes
        # (private CPython API that may break across versions).
        _heavy_executor.shutdown(wait=False, cancel_futures=True)
        _heavy_executor = None
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

    elapsed_s = time.monotonic() - started
    _consecutive_failures.pop(name, None)
    log.info("scheduler_loop_job_done", job=name, elapsed_ms=int(elapsed_s * 1000))
    scheduler_job_total.labels(job=name, status="success").inc()
    scheduler_job_duration_seconds.labels(job=name).observe(elapsed_s)
    return True


def _run_job(name: str, fn: Callable[[], Any], *, heavy: bool = False) -> bool:
    """Ejecuta un job ligero en un thread con timeout. Devuelve True si tuvo éxito.

    Para jobs pesados usa ``_run_heavy_job`` que emplea un proceso separado
    cancellable en timeout.

    Trackea fallos consecutivos por nombre de job para permitir backoff exponencial
    en el loop principal.
    """
    if heavy:
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
        exc = exc_holder[0]
        log.error(
            "scheduler_loop_job_failed",
            job=name,
            consecutive_failures=failures,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        notify(AlertLevel.ERROR, f"Scheduler job fallo: {name}", body=str(exc))
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
    return cast(timedelta, backed_off)


def _resolve_interval(job: ScheduledJob) -> timedelta:
    """Read the interval from the environment or fall back to the job's default."""
    # Some legacy env vars use _HOURS suffix; detect and convert.
    if job.interval_env.endswith("_HOURS"):
        hours = _env_int(job.interval_env, int(job.default_interval_minutes // 60))
        return timedelta(hours=hours)
    return timedelta(minutes=_env_int(job.interval_env, int(job.default_interval_minutes)))


def main() -> int:
    global _heavy_executor

    configure_logging(json_logs=os.environ.get("LOG_FORMAT") == "json")
    configure_tracing()
    configure_sentry(service="scheduler")

    # Registrar handlers para shutdown graceful (SIGTERM de Docker, SIGINT de Ctrl+C)
    def _handle_signal(signum: int, frame: object) -> None:
        log.info("scheduler_loop_shutdown_signal", signal=signum)
        _stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # ── Build schedule from the job registry ──────────────────────────
    registry = build_default_registry()
    sleep_seconds = _env_int("SCHEDULER_POLL_SECONDS", 60)

    now = datetime.now(UTC)
    intervals: dict[str, timedelta] = {}
    schedule: dict[str, datetime] = {}

    for job in registry:
        interval = _resolve_interval(job)
        intervals[job.name] = interval
        schedule[job.name] = now + timedelta(minutes=job.initial_offset_minutes)

    log.info(
        "scheduler_loop_start",
        jobs=[j.name for j in registry],
        intervals={name: int(iv.total_seconds() // 60) for name, iv in intervals.items()},
    )

    # Create the persistent process pool for heavy jobs
    _heavy_executor = concurrent.futures.ProcessPoolExecutor(max_workers=1)

    try:
        while True:
            now = datetime.now(UTC)
            for job in registry:
                if now >= schedule[job.name]:
                    _run_job(job.name, job.fn, heavy=job.heavy)
                    schedule[job.name] = now + _backoff_interval(job.name, intervals[job.name])
            # Esperar el poll interval o despertar inmediatamente si llega señal de parada
            if _stop_event.wait(timeout=sleep_seconds):
                log.info("scheduler_loop_stopped_gracefully")
                return 0
    finally:
        if _heavy_executor is not None:
            _heavy_executor.shutdown(wait=False, cancel_futures=True)
            _heavy_executor = None


if __name__ == "__main__":
    raise SystemExit(main())
