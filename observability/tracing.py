"""Integración OpenTelemetry para trazado distribuido.

Opera en **modo NoOp** si ``OTEL_EXPORTER_OTLP_ENDPOINT`` no está configurado,
de forma que no hay overhead ni dependencias activas en instalaciones básicas.

Uso típico:
    # En el entrypoint principal:
    from observability.tracing import configure_tracing
    configure_tracing()

    # En funciones a instrumentar:
    from observability.tracing import traced

    @traced("scraper.process_month")
    def process_month(year: int, month: int) -> dict: ...

El decorador ``@traced`` propaga automáticamente el ``run_id`` desde los
contextvars de structlog como atributo del span.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from observability.logging import get_logger

log = get_logger(__name__)


def _redact_span_text(text: str) -> str:
    """Redacta valores sensibles antes de enviarlos como atributo de span OTel.

    Reutiliza el cache de valores sensibles ya calculado por configure_logging()
    para evitar leer os.environ en cada excepción.
    """
    try:
        from observability.logging import _cached_sensitive_values

        result = text
        for sv in _cached_sensitive_values:
            if sv and sv in result:
                result = result.replace(sv, "***REDACTED***")
        return result
    except Exception:
        return text


F = TypeVar("F", bound=Callable[..., Any])

_configured = False
_noop = False


def configure_tracing(service_name: str | None = None) -> None:
    """Configura el TracerProvider global.

    Si ``OTEL_EXPORTER_OTLP_ENDPOINT`` no está configurado, instala un
    ``NoOpTracerProvider`` para que los decoradores ``@traced`` sean no-ops
    con overhead mínimo.

    Idempotente — puede llamarse varias veces sin efecto.
    """
    global _configured, _noop

    if _configured:
        return

    from config import settings

    endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    svc_name = service_name or settings.OTEL_SERVICE_NAME

    if not endpoint:
        # Sin endpoint configurado → modo NoOp (mínimo overhead)
        try:
            from opentelemetry import trace
            from opentelemetry.trace import NoOpTracerProvider

            trace.set_tracer_provider(NoOpTracerProvider())
        except ImportError:
            pass  # opentelemetry no instalado — silencio total
        _noop = True
        _configured = True
        log.debug("tracing_noop", reason="OTEL_EXPORTER_OTLP_ENDPOINT not set")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ParentBased,
            TraceIdRatioBased,
        )

        resource = Resource.create({"service.name": svc_name})

        # ── Adaptive sampling (J4) ──────────────────────────────────────
        # Default: 1 % of traces sampled (low traffic baseline).
        # Error spans are ALWAYS exported via _ErrorForceFlushProcessor
        # (a SpanProcessor approach, since samplers run before status is set).
        base_ratio = float(getattr(settings, "OTEL_SAMPLE_RATIO", 0.01))

        # NOTE: Samplers fire before span.set_status(ERROR) is called, so
        # checking error status in should_sample() is not reliable.
        # Instead, we use a SpanProcessor that force-exports on error.
        ratio_sampler = TraceIdRatioBased(base_ratio)
        # ParentBased respects parent sampling decision; for root spans uses ratio.
        sampler = ParentBased(root=ratio_sampler)

        provider = TracerProvider(resource=resource, sampler=sampler)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        batch_processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(batch_processor)

        # ── ErrorAlwaysExportProcessor ──────────────────────────────────
        # Ensures that spans ending with ERROR status are exported even when
        # they were NOT selected by the ratio sampler (dropped spans).
        # We achieve this by adding a SimpleSpanProcessor with a filter wrapper.
        try:
            from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter
            from opentelemetry.trace import StatusCode as _StatusCode

            class _ErrorFilterExporter(SpanExporter):
                """Exporter wrapper that only exports spans with ERROR status."""

                def __init__(self, inner: Any) -> None:
                    self._inner = inner

                def export(self, spans: Any) -> Any:
                    from opentelemetry.sdk.trace.export import SpanExportResult

                    error_spans = [
                        s
                        for s in spans
                        if getattr(getattr(s, "status", None), "status_code", None)
                        == _StatusCode.ERROR
                    ]
                    if error_spans:
                        return self._inner.export(error_spans)
                    return SpanExportResult.SUCCESS

                def shutdown(self) -> None:
                    pass

                def force_flush(self, timeout_millis: int = 30000) -> bool:
                    return True

            error_exporter = _ErrorFilterExporter(OTLPSpanExporter(endpoint=endpoint))
            provider.add_span_processor(SimpleSpanProcessor(error_exporter))
            log.debug("tracing_error_always_export_enabled")
        except Exception as _proc_exc:
            log.warning("tracing_error_processor_failed", error=str(_proc_exc))

        trace.set_tracer_provider(provider)
        _noop = False
        _configured = True
        log.info("tracing_configured", endpoint=endpoint, service=svc_name, sample_ratio=base_ratio)
    except ImportError as exc:
        log.warning(
            "tracing_import_error",
            error=str(exc),
            hint="Instala opentelemetry-sdk y opentelemetry-exporter-otlp-proto-http",
        )
        _noop = True
        _configured = True
    except Exception as exc:
        log.warning("tracing_setup_failed", error=str(exc))
        _noop = True
        _configured = True


def get_tracer(name: str) -> Any:
    """Retorna un tracer de OpenTelemetry (o NoOp si no está configurado)."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


class _NoOpTracer:
    """Tracer vacío para cuando opentelemetry no está disponible."""

    def start_as_current_span(self, name: str, **_kwargs: Any) -> Any:
        return _NoOpSpan()


class _NoOpSpan:
    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def set_attribute(self, *_: Any) -> None:
        pass

    def record_exception(self, *_: Any) -> None:
        pass

    def set_status(self, *_: Any) -> None:
        pass


def traced(span_name: str | None = None) -> Callable[[F], F]:
    """Decorador que envuelve una función con un span OpenTelemetry.

    Args:
        span_name: Nombre del span. Si es None, usa ``module.function_name``.

    Atributos automáticos añadidos al span:
        - ``run_id``: desde los contextvars de structlog (si disponible).
        - ``exception.type`` / ``exception.message``: en caso de excepción.

    Ejemplo::

        @traced("scraper.download_month")
        def download_month(year: int, month: int) -> Path | None: ...
    """

    def decorator(fn: F) -> F:
        name = span_name or f"{fn.__module__}.{fn.__qualname__}"

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _configured or _noop:
                # No se ha llamado configure_tracing(); ejecutar sin tracing
                return fn(*args, **kwargs)

            tracer = get_tracer(fn.__module__)
            with tracer.start_as_current_span(name) as span:
                # Propagar run_id desde structlog contextvars
                try:
                    from structlog.contextvars import get_contextvars

                    ctx = get_contextvars()
                    if "run_id" in ctx:
                        span.set_attribute("run_id", str(ctx["run_id"]))
                    if "session_hash" in ctx:
                        span.set_attribute("session.hash", str(ctx["session_hash"]))
                except Exception:
                    log.debug("span_contextvars_propagation_failed", exc_info=True)

                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    try:
                        from opentelemetry.trace import StatusCode

                        span.record_exception(exc)
                        span.set_status(StatusCode.ERROR, _redact_span_text(str(exc)))
                    except Exception:
                        log.debug("span_record_exception_failed", exc_info=True)
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator
