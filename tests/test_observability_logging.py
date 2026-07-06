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
    redact_dsn,
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


def test_redact_value_exact_match_short_circuits(capsys, monkeypatch):
    """Si el valor de un campo coincide EXACTO con un secreto cacheado, se
    redacta directo (rama distinta del reemplazo de subcadena incrustada)."""
    secret = "exact-match-secret-value"  # pragma: allowlist secret
    monkeypatch.setenv("API_HMAC_SECRET", secret)
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info("event_exact", raw_value=secret)
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "event_exact")
    assert data["raw_value"] == "***REDACTED***"


# ── Redacción de DSN Postgres/Supabase ───────────────────────────────────


def test_redact_dsn_masks_password():
    dsn = "postgresql://tenderflow:s3cr3tPass@db.pooler.supabase.com:5432/postgres?sslmode=verify-full"  # pragma: allowlist secret
    red = redact_dsn(dsn)
    assert "s3cr3tPass" not in red
    assert red.startswith("postgresql://tenderflow:***@")
    assert "sslmode=verify-full" in red  # se preserva lo no sensible


def test_redact_dsn_noop_without_dsn():
    assert redact_dsn("no hay dsn aquí") == "no hay dsn aquí"


def test_log_redacts_embedded_dsn_password(capsys):
    """Una password en un DSN se redacta aunque no coincida con ninguna env var."""
    configure_logging(level="INFO", json_logs=True)
    log = get_logger("tests.redact")
    log.info(
        "pg_connect_failed",
        error="could not connect to postgresql://u:topsecretpw@h:5432/db",  # pragma: allowlist secret
    )
    out = capsys.readouterr().err + capsys.readouterr().out
    data = _find_event(out, "pg_connect_failed")
    assert "topsecretpw" not in data["error"]
    assert "u:***@" in data["error"]


# ── bind_session_context ─────────────────────────────────────────────────


def test_bind_session_context_returns_none():
    """bind_session_context always returns None (Streamlit removed)."""
    result = bind_session_context()
    assert result is None
