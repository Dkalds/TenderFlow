"""Tests para observability/tracing.py — modo NoOp y decorador @traced."""

from __future__ import annotations


def _reset_tracing():
    """Resetea el estado del módulo de tracing para tests aislados."""
    import observability.tracing as tracing_mod

    tracing_mod._configured = False
    tracing_mod._noop = False


# ── configure_tracing en modo NoOp ────────────────────────────────────────────


def test_configure_tracing_noop_without_endpoint(monkeypatch):
    """Sin OTEL_EXPORTER_OTLP_ENDPOINT, configure_tracing activa modo NoOp."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    _reset_tracing()

    from observability.tracing import configure_tracing

    configure_tracing()

    import observability.tracing as tracing_mod

    assert tracing_mod._noop is True
    assert tracing_mod._configured is True


def test_configure_tracing_is_idempotent(monkeypatch):
    """configure_tracing se puede llamar múltiples veces sin efecto."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    _reset_tracing()

    from observability.tracing import configure_tracing

    configure_tracing()
    configure_tracing()  # segunda llamada — no debe lanzar

    import observability.tracing as tracing_mod

    assert tracing_mod._configured is True


# ── decorador @traced ─────────────────────────────────────────────────────────


def test_traced_noop_calls_function(monkeypatch):
    """El decorador @traced en modo NoOp ejecuta la función normalmente."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    _reset_tracing()

    from observability.tracing import configure_tracing, traced

    configure_tracing()

    call_log: list[str] = []

    @traced("test.operation")
    def my_func(x: int, y: int) -> int:
        call_log.append("called")
        return x + y

    result = my_func(2, 3)
    assert result == 5
    assert call_log == ["called"]


def test_traced_noop_propagates_exceptions(monkeypatch):
    """El decorador @traced en modo NoOp propaga excepciones correctamente."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    _reset_tracing()

    from observability.tracing import configure_tracing, traced

    configure_tracing()

    @traced("test.failing")
    def failing_func() -> None:
        raise ValueError("expected error")

    import pytest

    with pytest.raises(ValueError, match="expected error"):
        failing_func()


def test_traced_preserves_function_name(monkeypatch):
    """El decorador @traced preserva el nombre de la función decorada."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    _reset_tracing()

    from observability.tracing import traced

    @traced("test.named")
    def my_named_func() -> None:
        pass

    assert my_named_func.__name__ == "my_named_func"


# ── _redact_span_text ─────────────────────────────────────────────────────────


def test_redact_span_text_returns_string():
    """_redact_span_text devuelve una cadena sin lanzar excepciones."""
    from observability.tracing import _redact_span_text

    result = _redact_span_text("some text with sensitive info")
    assert isinstance(result, str)


def test_redact_span_text_empty_input():
    """_redact_span_text maneja cadena vacía sin error."""
    from observability.tracing import _redact_span_text

    result = _redact_span_text("")
    assert result == ""
