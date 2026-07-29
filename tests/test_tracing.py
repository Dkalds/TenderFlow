"""Tests para observability/tracing.py — modo NoOp y decorador @traced."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


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


# ── Bug #56: bypass sin configure_tracing ─────────────────────────────────────


def test_traced_bypasses_without_configure():
    """@traced debe hacer bypass si configure_tracing() nunca se llamó (issue #56)."""
    _reset_tracing()

    from observability.tracing import traced

    call_log: list[str] = []

    @traced("test.unconfigured")
    def my_func(x: int) -> int:
        call_log.append("called")
        return x * 2

    result = my_func(5)
    assert result == 10
    assert call_log == ["called"]


def test_traced_bypasses_noop_configured(monkeypatch):
    """@traced debe hacer bypass cuando _noop=True y _configured=True."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    _reset_tracing()

    from observability.tracing import configure_tracing, traced

    configure_tracing()

    import observability.tracing as tracing_mod

    assert tracing_mod._noop is True
    assert tracing_mod._configured is True

    call_log: list[str] = []

    @traced("test.noop_configured")
    def my_func() -> str:
        call_log.append("called")
        return "ok"

    result = my_func()
    assert result == "ok"
    assert call_log == ["called"]


# ── _redact_span_text — casos adicionales con _cached_sensitive_values ────────


class TestRedactSpanText:
    """Lines 43-44, 46-47: _redact_span_text."""

    def test_redact_sensitive_value(self):
        from observability.tracing import _redact_span_text

        with patch("observability.logging._cached_sensitive_values", ["secret123"]):
            result = _redact_span_text("error with secret123 in it")
            assert "secret123" not in result
            assert "***REDACTED***" in result

    def test_redact_exception_returns_original(self):
        from observability.tracing import _redact_span_text

        with patch("observability.logging._cached_sensitive_values", side_effect=AttributeError):
            result = _redact_span_text("some text")
            assert result == "some text"

    def test_redact_no_match(self):
        from observability.tracing import _redact_span_text

        with patch("observability.logging._cached_sensitive_values", ["xyz"]):
            result = _redact_span_text("no match here")
            assert result == "no match here"


# ── configure_tracing — ramas adicionales (idempotencia, ImportError) ────────


class TestConfigureTracing:
    """Lines 79-81, 89-174: configure_tracing branches."""

    def setup_method(self):
        import observability.tracing as t

        self._orig_configured = t._configured
        self._orig_noop = t._noop
        t._configured = False
        t._noop = False

    def teardown_method(self):
        import observability.tracing as t

        t._configured = self._orig_configured
        t._noop = self._orig_noop

    def test_idempotent(self):
        import observability.tracing as t

        t._configured = True
        t._noop = True
        t.configure_tracing()  # should return immediately
        assert t._noop is True

    def test_noop_mode_no_endpoint(self):
        import observability.tracing as t

        settings = MagicMock()
        settings.OTEL_EXPORTER_OTLP_ENDPOINT = ""
        settings.OTEL_SERVICE_NAME = "test"
        with patch("config.settings", settings):
            t.configure_tracing()
        assert t._configured is True
        assert t._noop is True

    def test_noop_mode_import_error(self):
        import observability.tracing as t

        settings = MagicMock()
        settings.OTEL_EXPORTER_OTLP_ENDPOINT = ""
        settings.OTEL_SERVICE_NAME = "test"

        import builtins as _builtins

        original_import = _builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "opentelemetry" in name:
                raise ImportError("no otel")
            return original_import(name, *args, **kwargs)

        with patch("config.settings", settings):
            with patch("builtins.__import__", side_effect=mock_import):
                t.configure_tracing()
        assert t._configured is True
        assert t._noop is True

    def test_full_setup_import_error(self):
        import observability.tracing as t

        settings = MagicMock()
        settings.OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4318"
        settings.OTEL_SERVICE_NAME = "test-svc"

        import builtins as _builtins

        original_import = _builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "opentelemetry" in name:
                raise ImportError("no otel sdk")
            return original_import(name, *args, **kwargs)

        with patch("config.settings", settings):
            with patch("builtins.__import__", side_effect=mock_import):
                t.configure_tracing()
        assert t._configured is True
        assert t._noop is True


# ── _NoOpTracer / _NoOpSpan ───────────────────────────────────────────────────


class TestNoOpTracerAndSpan:
    """Lines 182, 202, 205, 208: NoOp classes."""

    def test_noop_tracer(self):
        from observability.tracing import _NoOpSpan, _NoOpTracer

        tracer = _NoOpTracer()
        span = tracer.start_as_current_span("test")
        assert isinstance(span, _NoOpSpan)

    def test_noop_span_context_manager(self):
        from observability.tracing import _NoOpSpan

        span = _NoOpSpan()
        with span as s:
            s.set_attribute("key", "val")
            s.record_exception(Exception("err"))
            s.set_status("ERROR")


# ── traced() — tracing activo (no NoOp) ───────────────────────────────────────


class TestTracedDecorator:
    """Lines 236-260: traced decorator with active tracing."""

    def test_traced_noop(self):
        import observability.tracing as t

        orig_c, orig_n = t._configured, t._noop
        t._configured = False
        t._noop = False

        from observability.tracing import traced

        @traced("test.fn")
        def my_fn():
            return 42

        assert my_fn() == 42
        t._configured, t._noop = orig_c, orig_n

    def test_traced_configured_noop(self):
        import observability.tracing as t

        orig_c, orig_n = t._configured, t._noop
        t._configured = True
        t._noop = True

        from observability.tracing import traced

        @traced("test.fn2")
        def my_fn():
            return 99

        assert my_fn() == 99
        t._configured, t._noop = orig_c, orig_n

    def test_traced_active_success(self):
        import observability.tracing as t

        orig_c, orig_n = t._configured, t._noop
        t._configured = True
        t._noop = False

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        from observability.tracing import traced

        with patch("observability.tracing.get_tracer", return_value=mock_tracer):
            with patch(
                "structlog.contextvars.get_contextvars",
                return_value={"run_id": "r1", "session_hash": "s1"},
            ):

                @traced("test.fn3")
                def my_fn():
                    return 7

                assert my_fn() == 7
        t._configured, t._noop = orig_c, orig_n

    def test_traced_active_exception(self):
        import observability.tracing as t

        orig_c, orig_n = t._configured, t._noop
        t._configured = True
        t._noop = False

        # Use a real context manager mock
        inner_span = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=inner_span)
        mock_cm.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_cm

        mock_status_code = MagicMock()
        mock_status_code.ERROR = "ERROR"

        from observability.tracing import traced

        with patch("observability.tracing.get_tracer", return_value=mock_tracer):
            with patch.dict(
                "sys.modules", {"opentelemetry.trace": MagicMock(StatusCode=mock_status_code)}
            ):

                @traced("test.fn4")
                def my_fn():
                    raise ValueError("boom")

                with pytest.raises(ValueError, match="boom"):
                    my_fn()

        inner_span.record_exception.assert_called()
        t._configured, t._noop = orig_c, orig_n
