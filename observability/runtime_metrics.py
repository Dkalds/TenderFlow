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
    from prometheus_client import Counter, Gauge

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
    _AVAILABLE = False
