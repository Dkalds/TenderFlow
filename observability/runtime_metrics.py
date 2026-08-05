"""Métricas runtime de Prometheus expuestas en proceso (D1 + D2).

Estas gauges/counters viven en el ``REGISTRY`` por defecto y se exponen
vía ``/metrics`` del API. A diferencia de ``observability.prometheus`` (que
usa textfile collector para el scheduler), estas son in-process.

D2: el import de ``prometheus_client`` está protegido — si no está
instalado, las métricas son no-ops y la app sigue funcionando.
"""

from __future__ import annotations

from observability.logging import get_logger

log = get_logger(__name__)

try:
    from prometheus_client import Counter, Gauge, Histogram

    scraper_circuit_state = Gauge(
        "scraper_circuit_state",
        "Estado del circuit breaker (0=closed, 1=half-open, 2=open)",
        ["source"],
    )

    api_cost_estimate_total = Counter(
        "api_cost_estimate_total",
        "Coste estimado acumulado de operaciones (USD * 1e6, micros)",
        ["operation"],
    )

    audit_events_total = Counter(
        "audit_events_total",
        "Eventos de auditoría registrados",
        ["event_type", "outcome"],
    )

    scraper_circuit_transitions_total = Counter(
        "scraper_circuit_transitions_total",
        "Número de transiciones del circuit breaker entre estados",
        ["from_state", "to_state"],
    )

    ml_inference_duration_seconds = Histogram(
        "ml_inference_duration_seconds",
        "Latencia de inferencia ML (predict/predict_batch/predict_proba)",
        ["method"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler_job_total = Counter(
        "scheduler_job_total",
        "Número de ejecuciones de jobs del scheduler",
        ["job", "status"],  # status: success | timeout | error | skipped
    )

    scheduler_job_duration_seconds = Histogram(
        "scheduler_job_duration_seconds",
        "Duración de ejecución de jobs del scheduler",
        ["job"],
        buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0),
    )

    # ── DB pool ───────────────────────────────────────────────────────────────
    db_pool_size = Gauge(
        "db_pool_size",
        "Tamaño configurado del pool de conexiones DB",
    )

    db_pool_acquire_timeout_total = Counter(
        "db_pool_acquire_timeout_total",
        "Número de veces que el pool de conexiones DB agotó el timeout de adquisición",
    )

    # ── DB write health ───────────────────────────────────────────────────
    db_write_duration_seconds = Histogram(
        "db_write_duration_seconds",
        "Latencia de commits de escritura a la BD (alerta PgWriteLatencyHigh: p99 >1s)",
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )

    db_concurrent_writers = Gauge(
        "db_concurrent_writers",
        "Número de escritores concurrentes activos contra la BD",
    )

    # ── Parser field completeness ─────────────────────────────────────────
    parser_field_null_total = Counter(
        "parser_field_null_total",
        "Licitaciones parseadas con campo crítico NULL (por campo)",
        ["field"],
    )

    parser_entries_total = Counter(
        "parser_entries_total",
        "Total de entries parseadas por el parser CODICE",
    )

    # ── Upsert row drops (RFC observabilidad-perdida-filas-upsert) ────────
    upsert_rows_dropped_total = Counter(
        "upsert_rows_dropped_total",
        "Filas descartadas silenciosamente por INSERT OR IGNORE (violación de constraint)",
        ["table"],
    )

    # ── LLM budget (RFC llm-dependencia-gestionada) ───────────────────────
    llm_budget_exceeded_total = Counter(
        "llm_budget_exceeded_total",
        "Checks de presupuesto LLM que encontraron la ventana agotada",
        ["window", "mode"],  # window: daily | monthly · mode: monitor | enforce
    )

    # ── Pliegos: fetch + chunking/embeddings (plan Pliegos+RAG, F8) ────────
    documentos_fetched_total = Counter(
        "documentos_fetched_total",
        "Documentos procesados por fetch_and_extract, por resultado",
        ["status"],  # extracted | error
    )

    documento_chunks_total = Counter(
        "documento_chunks_total",
        "Chunks con embedding insertados en documento_chunks",
    )

    # ── Pliegos: señal de tecnología (plan categorización-pliegos) ─────────
    pliego_tech_signal_total = Counter(
        "pliego_tech_signal_total",
        "Licitaciones puntuadas por señal de tecnología de pliego, por resultado",
        ["method", "status"],  # method: keywords | llm · status: scored | no_signal | error
    )

    pliego_tech_merge_total = Counter(
        "pliego_tech_merge_total",
        "Fusiones de señal de pliego hacia ml_tecnologias/licitacion_tecnologia_score",
        ["outcome"],  # ok | error
    )

    # ── Dedupe cross-fuente (RFC validacion-dedupe-linaje) ────────────────
    dedupe_marked_total = Counter(
        "dedupe_marked_total",
        "Pares marcados como duplicados cross-fuente por detect_duplicates",
        ["source_pair", "status"],  # status: confirmed | pending
    )

    dedupe_match_rate = Gauge(
        "dedupe_match_rate",
        "Fracción de filas nuevas evaluadas que resultó marcada en la última pasada",
        ["fuente"],
    )

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    log.warning("prometheus_client_unavailable_metrics_disabled")

    class _NoopMetric:
        def labels(self, **_: object) -> _NoopMetric:
            return self

        def set(self, _value: float) -> None: ...
        def inc(self, _value: float = 1) -> None: ...
        def observe(self, _value: float) -> None: ...

    scraper_circuit_state = _NoopMetric()  # type: ignore[assignment]
    api_cost_estimate_total = _NoopMetric()  # type: ignore[assignment]
    audit_events_total = _NoopMetric()  # type: ignore[assignment]
    scraper_circuit_transitions_total = _NoopMetric()  # type: ignore[assignment]
    ml_inference_duration_seconds = _NoopMetric()  # type: ignore[assignment]
    scheduler_job_total = _NoopMetric()  # type: ignore[assignment]
    scheduler_job_duration_seconds = _NoopMetric()  # type: ignore[assignment]
    db_pool_size = _NoopMetric()  # type: ignore[assignment]
    db_pool_acquire_timeout_total = _NoopMetric()  # type: ignore[assignment]
    db_write_duration_seconds = _NoopMetric()  # type: ignore[assignment]
    db_concurrent_writers = _NoopMetric()  # type: ignore[assignment]
    parser_field_null_total = _NoopMetric()  # type: ignore[assignment]
    parser_entries_total = _NoopMetric()  # type: ignore[assignment]
    upsert_rows_dropped_total = _NoopMetric()  # type: ignore[assignment]
    llm_budget_exceeded_total = _NoopMetric()  # type: ignore[assignment]
    documentos_fetched_total = _NoopMetric()  # type: ignore[assignment]
    documento_chunks_total = _NoopMetric()  # type: ignore[assignment]
    pliego_tech_signal_total = _NoopMetric()  # type: ignore[assignment]
    pliego_tech_merge_total = _NoopMetric()  # type: ignore[assignment]
    dedupe_marked_total = _NoopMetric()  # type: ignore[assignment]
    dedupe_match_rate = _NoopMetric()  # type: ignore[assignment]
    _AVAILABLE = False
