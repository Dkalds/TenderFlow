"""Tests para scheduler/run_update.py — lógica de orquestación del pipeline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# main() — modos de ejecución
# ---------------------------------------------------------------------------


def test_main_daily_returns_0_on_ok():
    """--daily con status ok devuelve código 0."""
    mock_result = {"status": "ok", "inserted": [], "modified": []}

    with (
        patch("scheduler.run_update.update_daily", return_value=mock_result),
        patch("scheduler.run_update.check_and_notify"),
        patch("scheduler.run_update.count_licitaciones", return_value=100),
        patch("sys.argv", ["run_update", "--daily"]),
    ):
        import importlib

        from scheduler import run_update

        importlib.reload(run_update)
        code = run_update.main()

    assert code == 0


def test_main_daily_returns_1_on_error_status():
    """--daily con status distinto de ok devuelve código 1."""
    mock_result = {"status": "error"}

    with (
        patch("scheduler.run_update.update_daily", return_value=mock_result),
        patch("sys.argv", ["run_update", "--daily"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 1


def test_main_recent_ok_returns_0():
    """Modo reciente sin fallos devuelve 0."""
    ok_results = [{"status": "ok", "nuevas": 5, "actualizadas": 2}]

    with (
        patch("scheduler.run_update.update_recent", return_value=ok_results),
        patch("scheduler.run_update.check_and_notify"),
        patch("scheduler.run_update.count_licitaciones", return_value=200),
        patch("sys.argv", ["run_update"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 0


def test_main_recent_with_failures_returns_1():
    """Modo reciente con meses fallidos devuelve 1 y notifica."""
    results = [
        {"status": "ok", "nuevas": 3, "actualizadas": 0},
        {"status": "error", "nuevas": 0, "actualizadas": 0, "year": 2024, "month": 1},
    ]

    with (
        patch("scheduler.run_update.update_recent", return_value=results),
        patch("scheduler.run_update.count_licitaciones", return_value=100),
        patch("scheduler.run_update.notify") as mock_notify,
        patch("sys.argv", ["run_update"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 1
    mock_notify.assert_called_once()


def test_main_fatal_exception_returns_1():
    """Excepción fatal en el pipeline devuelve 1 y notifica CRITICAL."""
    with (
        patch("scheduler.run_update.update_recent", side_effect=RuntimeError("boom")),
        patch("scheduler.run_update.notify") as mock_notify,
        patch("sys.argv", ["run_update"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 1
    call_args = mock_notify.call_args
    # Primer argumento posicional debe ser AlertLevel.CRITICAL
    from observability import AlertLevel

    assert call_args[0][0] == AlertLevel.CRITICAL


def test_main_backfill_ok():
    """--backfill sin fallos devuelve 0."""
    results = [{"status": "ok", "nuevas": 10, "actualizadas": 5}]

    with (
        patch("scheduler.run_update.backfill", return_value=results),
        patch("scheduler.run_update.check_and_notify"),
        patch("scheduler.run_update.count_licitaciones", return_value=300),
        patch("sys.argv", ["run_update", "--backfill", "2024", "1"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 0


# ---------------------------------------------------------------------------
# _handle_daily_result
# ---------------------------------------------------------------------------


def test_handle_daily_result_skips_on_non_ok():
    """Si status != ok, no se invoca check_and_notify ni notify."""
    log_mock = MagicMock()
    with (
        patch("scheduler.run_update.check_and_notify") as mock_wl,
        patch("scheduler.run_update.notify") as mock_notify,
        patch("scheduler.run_update.count_licitaciones", return_value=0),
    ):
        from scheduler import run_update

        run_update._handle_daily_result({"status": "error"}, log_mock)

    mock_wl.assert_not_called()
    mock_notify.assert_not_called()


def test_handle_daily_result_notifies_on_modifications():
    """Si hay modificaciones, se llama notify con AlertLevel.INFO."""
    log_mock = MagicMock()
    result = {
        "status": "ok",
        "inserted": ["LIC-001"],
        "modified": ["LIC-002", "LIC-003"],
    }

    with (
        patch("scheduler.run_update.check_and_notify"),
        patch("scheduler.run_update.count_licitaciones", return_value=50),
        patch("scheduler.run_update.notify") as mock_notify,
    ):
        from scheduler import run_update

        run_update._handle_daily_result(result, log_mock)

    mock_notify.assert_called_once()
    from observability import AlertLevel

    assert mock_notify.call_args[0][0] == AlertLevel.INFO


def test_handle_daily_result_no_notify_when_no_modifications():
    """Sin modificaciones no se llama notify."""
    log_mock = MagicMock()
    result = {"status": "ok", "inserted": ["LIC-001"], "modified": []}

    with (
        patch("scheduler.run_update.check_and_notify"),
        patch("scheduler.run_update.count_licitaciones", return_value=10),
        patch("scheduler.run_update.notify") as mock_notify,
    ):
        from scheduler import run_update

        run_update._handle_daily_result(result, log_mock)

    mock_notify.assert_not_called()


def test_handle_daily_result_watchlist_exception_is_logged():
    """Si check_and_notify lanza excepción, se loguea pero no propaga."""
    log_mock = MagicMock()
    result = {"status": "ok", "inserted": [], "modified": []}

    with (
        patch("scheduler.run_update.check_and_notify", side_effect=RuntimeError("wl error")),
        patch("scheduler.run_update.count_licitaciones", return_value=0),
        patch("scheduler.run_update.notify"),
    ):
        from scheduler import run_update

        # No debe lanzar excepción
        run_update._handle_daily_result(result, log_mock)

    log_mock.exception.assert_called_once_with("watchlist_alert_error_daily")
