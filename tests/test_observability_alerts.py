"""Tests para observability.alerts (envío SMTP directo)."""

from __future__ import annotations

from datetime import UTC
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pydantic import SecretStr

from observability.alerts import AlertLevel, _build_html, notify


def _patch_settings(monkeypatch, **kwargs):
    """Parchea atributos del singleton ``config.settings`` directamente.

    Reemplaza el patrón previo (``monkeypatch.setenv`` + ``importlib.reload``
    de ``config``/``config.settings``): recargar esos módulos reemplaza su
    instancia de ``Settings`` por una nueva, pero cualquier módulo que ya
    hizo ``from config import settings`` antes del reload (p. ej.
    ``db/connection.py``) sigue apuntando al objeto viejo -- desincronización
    detectada en la auditoría de migración F3b (2026-07-05): un test de este
    archivo dejaba ``db.connection`` con un ``settings`` obsoleto que
    contenía el ``DATABASE_URL`` real leído de ``.env``, contaminando tests
    posteriores en la misma sesión de pytest. ``observability/alerts.py`` lee
    ``settings`` con ``from config import settings`` dentro de cada función
    (no al nivel de módulo), así que mutar el atributo del singleton ya
    compartido -- sin reload, mismo patrón que ``tmp_db``/``monkeypatch`` --
    alcanza y no desincroniza nada.
    """
    from config import settings

    for key, value in kwargs.items():
        monkeypatch.setattr(settings, key, value)


def test_notify_below_min_level_is_noop(monkeypatch):
    _patch_settings(monkeypatch, ALERT_MIN_LEVEL="error")
    with patch("observability.alerts._send_smtp") as smtp:
        notify(AlertLevel.WARN, "t", "b")
    smtp.assert_not_called()


def test_notify_above_min_level_calls_smtp(monkeypatch):
    _patch_settings(monkeypatch, ALERT_MIN_LEVEL="warn")
    with patch("observability.alerts._send_smtp") as smtp:
        notify(AlertLevel.WARN, "título", "cuerpo", count=3)
    smtp.assert_called_once()
    args = smtp.call_args[0]
    assert args[0] == AlertLevel.WARN
    assert args[1] == "título"


def test_notify_critical_always_dispatched(monkeypatch):
    _patch_settings(monkeypatch, ALERT_MIN_LEVEL="warn")
    with patch("observability.alerts._send_smtp") as smtp:
        notify(AlertLevel.CRITICAL, "alerta crítica")
    smtp.assert_called_once()


def test_notify_accepts_string_level(monkeypatch):
    _patch_settings(monkeypatch, ALERT_MIN_LEVEL="warn")
    with patch("observability.alerts._send_smtp") as smtp:
        notify("error", "title", "body", foo="bar")
    smtp.assert_called_once()


def test_notify_unknown_string_level_defaults_to_warn(monkeypatch):
    _patch_settings(monkeypatch, ALERT_MIN_LEVEL="info")
    with patch("observability.alerts._send_smtp") as smtp:
        notify("unknown_level", "title")
    smtp.assert_called_once()


def test_alert_level_ordering():
    assert AlertLevel.INFO < AlertLevel.WARN < AlertLevel.ERROR < AlertLevel.CRITICAL


def test_send_smtp_skips_when_not_configured(monkeypatch):
    """Sin variables de entorno SMTP no intenta conectar."""
    _patch_settings(
        monkeypatch,
        ALERT_EMAIL_TO="",
        ALERT_SMTP_USER="",
        ALERT_SMTP_PASSWORD=SecretStr(""),
    )
    with patch("smtplib.SMTP") as mock_smtp:
        from observability.alerts import _send_smtp

        _send_smtp(AlertLevel.WARN, "t", "b", {})
    mock_smtp.assert_not_called()


def test_send_smtp_connects_and_sends(monkeypatch):
    """Con credenciales configuradas se conecta al servidor SMTP."""
    _patch_settings(
        monkeypatch,
        ALERT_EMAIL_TO="dest@example.com",
        ALERT_SMTP_USER="sender@gmail.com",
        ALERT_SMTP_PASSWORD=SecretStr("app-password-16ch"),
        ALERT_SMTP_HOST="smtp.gmail.com",
        ALERT_SMTP_PORT=587,
    )

    mock_server = MagicMock()
    mock_server.__enter__ = lambda s: s
    mock_server.__exit__ = MagicMock(return_value=False)

    with patch("smtplib.SMTP", return_value=mock_server):
        from observability.alerts import _send_smtp

        _send_smtp(AlertLevel.ERROR, "Test error", "algo falló", {"run_id": "abc"})

    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("sender@gmail.com", "app-password-16ch")
    mock_server.sendmail.assert_called_once()
    # Verifica que el destinatario es el correcto
    _, call_args, _ = mock_server.sendmail.mock_calls[0]
    assert "dest@example.com" in call_args[1]


def test_build_html_contains_title_and_body():
    html = _build_html(AlertLevel.ERROR, "Mi título", "Descripción del error", {"run": "r1"})
    assert "Mi título" in html
    assert "Descripción del error" in html
    assert "run" in html
    assert "r1" in html


def test_build_html_uses_level_color():
    html_warn = _build_html(AlertLevel.WARN, "t", "b", {})
    html_crit = _build_html(AlertLevel.CRITICAL, "t", "b", {})
    assert "#e6a817" in html_warn  # color WARN
    assert "#8b0000" in html_crit  # color CRITICAL


def test_send_smtp_logs_on_smtp_exception(monkeypatch):
    """SMTPException debe loguear warning y no relanzar."""
    import smtplib

    _patch_settings(
        monkeypatch,
        ALERT_EMAIL_TO="dest@example.com",
        ALERT_SMTP_USER="sender@gmail.com",
        ALERT_SMTP_PASSWORD=SecretStr("app-password-16ch"),
        ALERT_SMTP_HOST="smtp.gmail.com",
        ALERT_SMTP_PORT=587,
    )

    mock_server = MagicMock()
    mock_server.__enter__ = lambda s: s
    mock_server.__exit__ = MagicMock(return_value=False)
    mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"auth failed")

    with patch("smtplib.SMTP", return_value=mock_server):
        from observability.alerts import _send_smtp

        # No debe lanzar excepción — solo loguea
        _send_smtp(AlertLevel.ERROR, "t", "b", {})


def test_send_smtp_logs_on_os_error(monkeypatch):
    """OSError (fallo de red) debe loguear warning y no relanzar."""
    _patch_settings(
        monkeypatch,
        ALERT_EMAIL_TO="dest@example.com",
        ALERT_SMTP_USER="sender@gmail.com",
        ALERT_SMTP_PASSWORD=SecretStr("pass"),
        ALERT_SMTP_HOST="badhost",
        ALERT_SMTP_PORT=587,
    )

    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        from observability.alerts import _send_smtp

        _send_smtp(AlertLevel.WARN, "t", "b", {})


# ---------------------------------------------------------------------------
# check_daily_lag
# ---------------------------------------------------------------------------


def test_check_daily_lag_no_cursor_is_noop(tmp_db):
    _, _ = tmp_db
    from observability.alerts import check_daily_lag

    with patch("observability.alerts.notify") as mock_notify:
        check_daily_lag()
    mock_notify.assert_not_called()


def test_check_daily_lag_fresh_cursor_no_alert(tmp_db, monkeypatch):
    _, _ = tmp_db
    from datetime import datetime

    from observability.alerts import check_daily_lag

    now_iso = datetime.now(UTC).isoformat()
    with (
        patch("db.database.get_cursor", return_value={"last_seen_updated": now_iso}),
        patch("observability.alerts.notify") as mock_notify,
    ):
        check_daily_lag()
    mock_notify.assert_not_called()


def test_check_daily_lag_stale_cursor_sends_alert(monkeypatch):
    from observability.alerts import check_daily_lag

    old_ts = "2020-01-01T00:00:00+00:00"
    with (
        patch("db.database.get_cursor", return_value={"last_seen_updated": old_ts}),
        patch("observability.alerts.notify") as mock_notify,
    ):
        check_daily_lag()
    mock_notify.assert_called_once()
    assert "lag" in mock_notify.call_args[0][1].lower()


def test_check_daily_lag_invalid_timestamp_no_crash(monkeypatch):
    from observability.alerts import check_daily_lag

    with (
        patch("db.database.get_cursor", return_value={"last_seen_updated": "NOT_A_DATE"}),
        patch("observability.alerts.notify") as mock_notify,
    ):
        check_daily_lag()
    mock_notify.assert_not_called()


# ---------------------------------------------------------------------------
# check_daily_consecutive_failures
# ---------------------------------------------------------------------------


def test_check_consecutive_failures_not_enough_rows(tmp_db):
    _, _ = tmp_db
    from observability.alerts import check_daily_consecutive_failures

    with patch("observability.alerts.notify") as mock_notify:
        check_daily_consecutive_failures()
    mock_notify.assert_not_called()


def test_check_consecutive_failures_sends_alert(tmp_db):
    db_mod, _ = tmp_db
    from observability.alerts import (
        _DAILY_MAX_CONSECUTIVE_FAILURES,
        check_daily_consecutive_failures,
    )

    # Insertar N runs con status="error"
    with db_mod.connect() as c:
        for i in range(_DAILY_MAX_CONSECUTIVE_FAILURES):
            c.execute(
                "INSERT INTO extraction_runs (run_id, started_at, status, notas) "
                "VALUES (%s, %s, %s, %s)",
                (f"run-{uuid4()}", f"2024-01-0{i + 1}T00:00:00", "error", "daily|test"),
            )

    with patch("observability.alerts.notify") as mock_notify:
        check_daily_consecutive_failures()
    mock_notify.assert_called_once()
    assert "fallo" in mock_notify.call_args[0][1].lower()


def test_check_consecutive_failures_mixed_status_no_alert(tmp_db):
    db_mod, _ = tmp_db
    from observability.alerts import (
        _DAILY_MAX_CONSECUTIVE_FAILURES,
        check_daily_consecutive_failures,
    )

    with db_mod.connect() as c:
        c.execute(
            "INSERT INTO extraction_runs (run_id, started_at, status, notas) VALUES (%s, %s, %s, %s)",
            (f"run-{uuid4()}", "2024-01-01T00:00:00", "ok", "daily|test"),
        )
        for i in range(_DAILY_MAX_CONSECUTIVE_FAILURES - 1):
            c.execute(
                "INSERT INTO extraction_runs (run_id, started_at, status, notas) "
                "VALUES (%s, %s, %s, %s)",
                (f"run-{uuid4()}", f"2024-01-0{i + 2}T00:00:00", "error", "daily|test"),
            )

    with patch("observability.alerts.notify") as mock_notify:
        check_daily_consecutive_failures()
    mock_notify.assert_not_called()
