"""Métricas runtime de Prometheus expuestas en proceso (D1 + D2).

Estas gauges/counters viven en el ``REGISTRY`` por defecto y se exponen
vía ``/metrics`` del API. A diferencia de ``observability.prometheus`` (que
usa textfile collector para el scheduler), estas son in-process.

D2: el import de ``prometheus_client`` está protegido — si no está
instalado, las métricas son no-ops y la app sigue funcionando.
"""

from __future__ import annotations

from typing import Protocol, Self

from observability.logging import get_logger

log = get_logger(__name__)


# Contratos que cumplen a la vez la métrica real de ``prometheus_client`` y
# ``_NoopMetric``. Las variables se anotan con ellos y no con ``Counter``,
# ``Gauge`` o ``Histogram`` porque sin la librería el módulo publica la no-op:
# un llamador que usara algo fuera de este subconjunto (``.time()``, ``.dec()``…)
# pasaría mypy y los tests y reventaría justo en la instalación mínima que D2
# promete soportar. Los parámetros son solo posicionales para que su nombre no
# forme parte del contrato — la no-op los llama ``_value``. Las etiquetas son
# ``object`` porque ``prometheus_client`` les aplica ``str()``, y hay llamadores
# que se apoyan en ello (el nombre de un breaker de ``pybreaker`` es opcional).
class _Metric(Protocol):
    def labels(self, *labelvalues: object, **labelkwargs: object) -> Self: ...


class _CounterMetric(_Metric, Protocol):
    def inc(self, amount: float = 1, /) -> None: ...


class _GaugeMetric(_Metric, Protocol):
    def inc(self, amount: float = 1, /) -> None: ...
    def set(self, value: float, /) -> None: ...


class _HistogramMetric(_Metric, Protocol):
    def observe(self, amount: float, /) -> None: ...


try:
    from prometheus_client import Counter, Gauge, Histogram

    scraper_circuit_state: _GaugeMetric = Gauge(
        "scraper_circuit_state",
        "Estado del circuit breaker (0=closed, 1=half-open, 2=open)",
        ["source"],
    )

    api_cost_estimate_total: _CounterMetric = Counter(
        "api_cost_estimate_total",
        "Coste estimado acumulado de operaciones (USD * 1e6, micros)",
        ["operation"],
    )

    audit_events_total: _CounterMetric = Counter(
        "audit_events_total",
        "Eventos de auditoría registrados",
        ["event_type", "outcome"],
    )

    scraper_circuit_transitions_total: _CounterMetric = Counter(
        "scraper_circuit_transitions_total",
        "Número de transiciones del circuit breaker entre estados",
        ["from_state", "to_state"],
    )

    ml_inference_duration_seconds: _HistogramMetric = Histogram(
        "ml_inference_duration_seconds",
        "Latencia de inferencia ML (predict/predict_batch/predict_proba)",
        ["method"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler_job_total: _CounterMetric = Counter(
        "scheduler_job_total",
        "Número de ejecuciones de jobs del scheduler",
        ["job", "status"],  # status: success | timeout | error | skipped
    )

    scheduler_job_duration_seconds: _HistogramMetric = Histogram(
        "scheduler_job_duration_seconds",
        "Duración de ejecución de jobs del scheduler",
        ["job"],
        buckets=(1.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0),
    )

    # ── DB pool ───────────────────────────────────────────────────────────────
    # Etiquetadas por pool: hay uno de escritura y otro de lectura (ADR-025).
    db_pool_size: _GaugeMetric = Gauge(
        "db_pool_size",
        "Tamaño máximo configurado del pool de conexiones DB",
        ["pool"],
    )

    db_pool_connections: _GaugeMetric = Gauge(
        "db_pool_connections",
        "Conexiones del pool por estado (available: libres en el pool; used: en uso)",
        ["pool", "state"],
    )

    db_pool_requests_waiting: _GaugeMetric = Gauge(
        "db_pool_requests_waiting",
        "Peticiones encoladas esperando una conexión libre del pool",
        ["pool"],
    )

    db_pool_acquire_timeout_total: _CounterMetric = Counter(
        "db_pool_acquire_timeout_total",
        "Número de veces que el pool de conexiones DB agotó el timeout de adquisición",
    )

    # ── DB write health ───────────────────────────────────────────────────
    db_write_duration_seconds: _HistogramMetric = Histogram(
        "db_write_duration_seconds",
        "Latencia de commits de escritura a la BD (alerta PgWriteLatencyHigh: p99 >1s)",
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )

    # ── DB read health ────────────────────────────────────────────────────
    # Simétrica a la de escritura: hasta 2026-08 solo se medía el 49% del
    # tráfico (los commits), y las 209 rutas de lectura eran invisibles.
    db_read_duration_seconds: _HistogramMetric = Histogram(
        "db_read_duration_seconds",
        "Latencia de los bloques de lectura (connect_read) contra la BD",
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    )

    db_concurrent_writers: _GaugeMetric = Gauge(
        "db_concurrent_writers",
        "Número de escritores concurrentes activos contra la BD",
    )

    # ── Parser field completeness ─────────────────────────────────────────
    parser_field_null_total: _CounterMetric = Counter(
        "parser_field_null_total",
        "Licitaciones parseadas con campo crítico NULL (por campo)",
        ["field"],
    )

    parser_entries_total: _CounterMetric = Counter(
        "parser_entries_total",
        "Total de entries parseadas por el parser CODICE",
    )

    # ── Upsert row drops (RFC observabilidad-perdida-filas-upsert) ────────
    upsert_rows_dropped_total: _CounterMetric = Counter(
        "upsert_rows_dropped_total",
        "Filas descartadas silenciosamente por INSERT OR IGNORE (violación de constraint)",
        ["table"],
    )

    # ── LLM budget (RFC llm-dependencia-gestionada) ───────────────────────
    llm_budget_exceeded_total: _CounterMetric = Counter(
        "llm_budget_exceeded_total",
        "Checks de presupuesto LLM que encontraron la ventana agotada",
        ["window", "mode"],  # window: daily | monthly · mode: monitor | enforce
    )

    # ── Pliegos: fetch + chunking/embeddings (plan Pliegos+RAG, F8) ────────
    documentos_fetched_total: _CounterMetric = Counter(
        "documentos_fetched_total",
        "Documentos procesados por fetch_and_extract, por resultado",
        ["status"],  # extracted | error
    )

    documento_chunks_total: _CounterMetric = Counter(
        "documento_chunks_total",
        "Chunks con embedding insertados en documento_chunks",
    )

    # ── Caché de respuestas del LLM (C5.5) ─────────────────────────────────
    # Con `resultado` como label y no dos contadores: un hit sin su miss no
    # dice nada — la métrica que importa es la RATIO, y para calcularla hacen
    # falta las dos series con la misma dimensionalidad.
    llm_cache_hit_total: _CounterMetric = Counter(
        "llm_cache_hit_total",
        "Consultas a la cache de respuestas LLM, por modo y resultado",
        ["modo", "resultado"],
    )

    # ── Pliegos: señal de tecnología (plan categorización-pliegos) ─────────
    pliego_tech_signal_total: _CounterMetric = Counter(
        "pliego_tech_signal_total",
        "Licitaciones puntuadas por señal de tecnología, por método y resultado",
        # method: keywords | llm | llm_metadata (este último no viene de pliegos
        # sino de la metadata del anuncio, pero comparte tabla, merge y contador)
        # · status: scored | no_signal | error
        ["method", "status"],
    )

    pliego_tech_merge_total: _CounterMetric = Counter(
        "pliego_tech_merge_total",
        "Fusiones de señal de pliego hacia ml_tecnologias/licitacion_tecnologia_score",
        ["outcome"],  # ok | error
    )

    # ── Dedupe cross-fuente (RFC validacion-dedupe-linaje) ────────────────
    dedupe_marked_total: _CounterMetric = Counter(
        "dedupe_marked_total",
        "Pares marcados como duplicados cross-fuente por detect_duplicates",
        ["source_pair", "status"],  # status: confirmed | pending
    )

    dedupe_match_rate: _GaugeMetric = Gauge(
        "dedupe_match_rate",
        "Fracción de filas nuevas evaluadas que resultó marcada en la última pasada",
        ["fuente"],
    )

    # ── Entrega de alertas (S6.3) ─────────────────────────────────────────
    # `observability/alerts.py` documenta que "nunca propaga": un buzón mal
    # configurado o un SMTP caído no pueden tumbar a quien llama, porque la
    # alerta describe algo que ya ocurrió. Esa propiedad es correcta y se
    # mantiene — pero convertía el fallo en INVISIBLE: el valor de retorno de
    # `_entregar_email` se descartaba, así que un ALERT_SMTP_PASSWORD caducado
    # dejaba de avisar sin que nadie se enterase. Es el peor modo de fallo
    # posible para un canal de alertas: silencioso y en el momento en que hace
    # falta. Este contador lo hace visible sin cambiar la propiedad.
    #
    # OJO al alcance: los planos EFÍMEROS (scraper/ML/pliegos/healthcheck en GH
    # Actions) NO son scrapeables —el proceso muere al terminar el job— y son
    # justamente los que más alertas envían. Ahí este contador solo alimenta el
    # log; la vigilancia de ese lado tiene que salir de `ops_events`
    # (scheduler/healthcheck.py).
    alert_delivery_failed_total: _CounterMetric = Counter(
        "alert_delivery_failed_total",
        "Alertas que no llegaron a salir del proceso (canal de alertas roto)",
        ["canal", "motivo"],  # canal: email · motivo: not_configured|smtp|network
    )

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    log.warning("prometheus_client_unavailable_metrics_disabled")

    class _NoopMetric:
        def labels(self, *_args: object, **_kwargs: object) -> _NoopMetric:
            return self

        def set(self, _value: float) -> None: ...
        def inc(self, _value: float = 1) -> None: ...
        def observe(self, _value: float) -> None: ...

    scraper_circuit_state = _NoopMetric()
    api_cost_estimate_total = _NoopMetric()
    audit_events_total = _NoopMetric()
    scraper_circuit_transitions_total = _NoopMetric()
    ml_inference_duration_seconds = _NoopMetric()
    scheduler_job_total = _NoopMetric()
    scheduler_job_duration_seconds = _NoopMetric()
    db_pool_size = _NoopMetric()
    db_pool_connections = _NoopMetric()
    db_pool_requests_waiting = _NoopMetric()
    db_pool_acquire_timeout_total = _NoopMetric()
    db_write_duration_seconds = _NoopMetric()
    db_read_duration_seconds = _NoopMetric()
    db_concurrent_writers = _NoopMetric()
    parser_field_null_total = _NoopMetric()
    parser_entries_total = _NoopMetric()
    upsert_rows_dropped_total = _NoopMetric()
    llm_budget_exceeded_total = _NoopMetric()
    documentos_fetched_total = _NoopMetric()
    documento_chunks_total = _NoopMetric()
    llm_cache_hit_total = _NoopMetric()
    pliego_tech_signal_total = _NoopMetric()
    pliego_tech_merge_total = _NoopMetric()
    dedupe_marked_total = _NoopMetric()
    dedupe_match_rate = _NoopMetric()
    alert_delivery_failed_total = _NoopMetric()
    _AVAILABLE = False


def refresh_db_pool_metrics() -> None:
    """Vuelca el estado de los pools de BD en sus gauges.

    Se invoca al servir ``/metrics`` en vez de instrumentar cada ``getconn``:
    ``psycopg_pool`` ya lleva la contabilidad, y muestrearla en el scrape evita
    añadir trabajo al camino de cada petición. Sin esto, ``db_pool_size`` y
    compañía existían declaradas pero valían siempre 0 — la saturación del pool,
    que es el modo de fallo más probable bajo carga, era invisible.
    """
    try:
        from db.connection import pool_stats

        instantanea = pool_stats()
    except Exception:
        # La instrumentación nunca puede tumbar el endpoint que la expone: un
        # /metrics que devuelve 500 deja ciego al scrape entero, no solo a
        # estos gauges.
        log.debug("db_pool_metrics_unavailable", exc_info=True)
        return

    for pool_name, stats in instantanea.items():
        try:
            db_pool_size.labels(pool=pool_name).set(stats.get("pool_max", 0))
            db_pool_connections.labels(pool=pool_name, state="available").set(
                stats.get("pool_available", 0)
            )
            db_pool_connections.labels(pool=pool_name, state="used").set(
                max(stats.get("pool_size", 0) - stats.get("pool_available", 0), 0)
            )
            db_pool_requests_waiting.labels(pool=pool_name).set(stats.get("requests_waiting", 0))
        except Exception:  # pragma: no cover - métrica best-effort
            log.debug("db_pool_metrics_refresh_failed", pool=pool_name)
