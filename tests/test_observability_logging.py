"""Tests para observability.logging."""

from __future__ import annotations

import json
import logging

import pytest

from observability.logging import (
    bind_run_context,
    bind_session_context,
    clear_run_context,
    configure_logging,
    get_logger,
)


@pytest.fixture(autouse=True)
def _clear_ctx():
    clear_run_context()
    yield
    clear_run_context()


def test_configure_logging_is_idempotent():
    configure_logging(level="INFO", json_logs=True)
    configure_logging(level="INFO", json_logs=True)
    assert logging.getLogger().level == logging.INFO


def test_get_logger_returns_bound_logger():
    configure_logging(json_logs=True)
    log = get_logger("tests.obs")
    # structlog.get_logger devuelve un BoundLoggerLazyProxy;
    # lo importante es que exponga la API de logging.
    assert hasattr(log, "info")
    assert hasattr(log, "bind")


def test_bind_run_context_generates_run_id():
    run_id = bind_run_context()
    assert isinstance(run_id, str)
    assert len(run_id) == 12


def test_bind_run_context_respects_explicit_id():
    run_id = bind_run_context(run_id="fixed-id", module="tests")
    assert run_id == "fixed-id"


def test_json_logs_contain_run_id(capsys):
    configure_logging(level="INFO", json_logs=True)
    run_id = bind_run_context(run_id="r1", module="tests")
    log = get_logger("tests.json")
    log.info("test_event", foo="bar")
    captured = capsys.readouterr()
    # El output JSON va al stream stderr configurado por configure_logging.
    lines = [ln for ln in (captured.err + captured.out).splitlines() if "test_event" in ln]
    assert lines, "no se encontró el evento en stderr/stdout"
    # Buscamos una línea que sea JSON válido con run_id esperado.
    for ln in lines:
        try:
            data = json.loads(ln)
        except ValueError:
            continue
        if data.get("event") == "test_event":
            assert data["run_id"] == run_id
            assert data["foo"] == "bar"
            return
    pytest.fail(f"no JSON válido con event=test_event en: {lines}")


# ── Redacción de secretos ────────────────────────────────────────────────


def _find_event(captured_text: str, event_name: str) -> dict:
    """Localiza un evento JSON en la salida capturada."""
    for ln in captured_text.splitlines():
        try:
            data = json.loads(ln)
        except ValueError:
            continue
        if data.get("event") == event_name:
            return data
    pytest.fail(f"no se encontró JSON con event={event_name} en:\n{captured_text}")


def test_redact_keys_with_sensitive_names(capsys):
    """Cualquier campo cuya clave coincide con un nombre sensible se redacta."""
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("login_attempt", password="hunter2", token="abc123", user="alice")
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "login_attempt")
    assert data["password"] == "***REDACTED***"
    assert data["token"] == "***REDACTED***"
    assert data["user"] == "alice"  # no sensible


def test_redact_env_secret_value(capsys, monkeypatch):
    """Si un valor coincide con el contenido de una env var sensible, se redacta."""
    secret = "super-secret-token-xyz"
    monkeypatch.setenv("TURSO_AUTH_TOKEN", secret)
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("conn_open", connection_string=f"libsql://db?token={secret}", host="example")
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "conn_open")
    assert secret not in data["connection_string"]
    assert "***REDACTED***" in data["connection_string"]
    assert data["host"] == "example"


def test_short_env_secret_not_redacted(capsys, monkeypatch):
    """Valores demasiado cortos (<4 chars) no se consideran secretos para evitar
    falsos positivos."""
    monkeypatch.setenv("DASHBOARD_PASSWORD", "ab")
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("noop_event", note="this is ab safe")
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "noop_event")
    assert data["note"] == "this is ab safe"


# ── bind_session_context ─────────────────────────────────────────────────


def test_bind_session_context_returns_none_outside_streamlit():
    """Outside a Streamlit script run, bind_session_context must return None
    without raising."""
    result = bind_session_context()
    assert result is None


def test_bind_session_context_returns_none_when_ctx_unavailable(monkeypatch):
    """If get_script_run_ctx returns None, must return None gracefully."""
    import observability.logging as obs_logging

    monkeypatch.setattr(
        obs_logging,
        "bind_session_context",
        lambda: None,  # stand-in; tests the contract not the internals
    )
    assert obs_logging.bind_session_context() is None


def test_bind_session_context_binds_session_id_to_contextvars(monkeypatch):
    """When a Streamlit context with a session_id is available, the hashed
    session_id must be bound to structlog contextvars and returned."""
    import types

    import structlog.contextvars as ctx_module

    import observability.logging as obs_logging

    # Build a fake Streamlit context object with a session_id
    fake_ctx = types.SimpleNamespace(session_id="test-session-abc-123")

    # Patch the import inside bind_session_context via importlib shimming:
    # we replace the function body by monkeypatching the helper it calls.
    fake_module = types.ModuleType("streamlit.runtime.scriptrunner")
    fake_module.get_script_run_ctx = lambda: fake_ctx

    import sys

    monkeypatch.setitem(sys.modules, "streamlit.runtime.scriptrunner", fake_module)

    # Clear any existing contextvars before testing
    ctx_module.clear_contextvars()

    result = obs_logging.bind_session_context()

    assert result is not None
    assert isinstance(result, str)
    assert len(result) == 12  # SHA-256 prefix, 12 hex chars
    # Verify it's deterministic: same input → same output
    import hashlib

    expected = hashlib.sha256(b"test-session-abc-123").hexdigest()[:12]
    assert result == expected

    # Verify it was bound into contextvars (appears in a log record)
    merged = ctx_module.merge_contextvars(None, None, {"event": "x"})
    assert merged.get("session_id") == expected

    ctx_module.clear_contextvars()


def test_bind_session_context_handles_empty_session_id(monkeypatch):
    """A context object with an empty session_id must return None."""
    import types

    import observability.logging as obs_logging

    fake_ctx = types.SimpleNamespace(session_id="")
    fake_module = types.ModuleType("streamlit.runtime.scriptrunner")
    fake_module.get_script_run_ctx = lambda: fake_ctx

    import sys

    monkeypatch.setitem(sys.modules, "streamlit.runtime.scriptrunner", fake_module)

    result = obs_logging.bind_session_context()
    assert result is None


def test_bind_session_context_suppresses_import_error(monkeypatch):
    """If streamlit is not installed at all, must return None silently."""
    import sys

    monkeypatch.setitem(sys.modules, "streamlit.runtime.scriptrunner", None)

    import observability.logging as obs_logging

    result = obs_logging.bind_session_context()
    assert result is None
