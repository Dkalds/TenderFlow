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
        # Sin endpoint configurado → modo NoOp
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider

            provider = TracerProvider()
            trace.set_tracer_provider(provider)
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

        resource = Resource.create({"service.name": svc_name})
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _noop = False
        _configured = True
        log.info("tracing_configured", endpoint=endpoint, service=svc_name)
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
            if _noop and not _configured:
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
                    pass

                try:
                    return fn(*args, **kwargs)
                except Exception as exc:
                    try:
                        from opentelemetry.trace import StatusCode

                        span.record_exception(exc)
                        span.set_status(StatusCode.ERROR, _redact_span_text(str(exc)))
                    except Exception:
                        pass
                    raise

        return wrapper  # type: ignore[return-value]

    return decorator
