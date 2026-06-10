"""Tests para scheduler/run_update.py — lógica de orquestación del pipeline.

Actualizado para ADR-012: run_update.py ahora delega en pipeline_runs.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# main() — modos de ejecución (delegando en pipeline_runs)
# ---------------------------------------------------------------------------


def test_main_daily_returns_0_on_ok():
    """--daily con pipeline exitosa devuelve código 0."""
    pipeline_result = {
        "status": "ok",
        "ingestion_result": {"status": "ok", "inserted": [], "modified": []},
        "steps": {},
    }

    with (
        patch("scheduler.run_update.run_daily_pipeline", return_value=pipeline_result),
        patch("scheduler.run_update.count_licitaciones", return_value=100),
        patch("sys.argv", ["run_update", "--daily"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 0


def test_main_daily_returns_1_on_error():
    """--daily con pipeline que lanza excepción devuelve código 1."""
    with (
        patch(
            "scheduler.run_update.run_daily_pipeline",
            side_effect=RuntimeError("ingestion failed"),
        ),
        patch("scheduler.run_update.notify"),
        patch("sys.argv", ["run_update", "--daily"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 1


def test_main_recent_ok_returns_0():
    """Modo reciente sin fallos devuelve 0."""
    pipeline_result = {
        "status": "ok",
        "ingestion_results": [{"status": "ok", "nuevas": 5, "actualizadas": 2}],
        "steps": {},
    }

    with (
        patch("scheduler.run_update.run_bulk_pipeline", return_value=pipeline_result),
        patch("scheduler.run_update.count_licitaciones", return_value=200),
        patch("sys.argv", ["run_update"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 0


def test_main_recent_with_failures_returns_1():
    """Modo reciente con pipeline que falla devuelve 1 y notifica."""
    with (
        patch(
            "scheduler.run_update.run_bulk_pipeline",
            side_effect=RuntimeError("bulk failed for 1 month(s)"),
        ),
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
        patch(
            "scheduler.run_update.run_bulk_pipeline",
            side_effect=RuntimeError("boom"),
        ),
        patch("scheduler.run_update.notify") as mock_notify,
        patch("sys.argv", ["run_update"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 1
    call_args = mock_notify.call_args
    from observability import AlertLevel

    assert call_args[0][0] == AlertLevel.CRITICAL


def test_main_backfill_ok():
    """--backfill sin fallos devuelve 0."""
    pipeline_result = {
        "status": "ok",
        "ingestion_results": [{"status": "ok", "nuevas": 10, "actualizadas": 5}],
        "steps": {},
    }

    with (
        patch("scheduler.run_update.run_backfill_pipeline", return_value=pipeline_result),
        patch("scheduler.run_update.count_licitaciones", return_value=300),
        patch("sys.argv", ["run_update", "--backfill", "2024", "1"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 0


# ---------------------------------------------------------------------------
# _log_daily_summary
# ---------------------------------------------------------------------------


def test_log_daily_summary_notifies_on_modifications():
    """Si hay modificaciones, se llama notify con AlertLevel.INFO."""
    log_mock = MagicMock()
    pipeline_result = {
        "status": "ok",
        "ingestion_result": {
            "status": "ok",
            "inserted": ["LIC-001"],
            "modified": ["LIC-002", "LIC-003"],
        },
        "steps": {},
    }

    with (
        patch("scheduler.run_update.count_licitaciones", return_value=50),
        patch("scheduler.run_update.notify") as mock_notify,
    ):
        from scheduler import run_update

        run_update._log_daily_summary(pipeline_result, log_mock)

    mock_notify.assert_called_once()
    from observability import AlertLevel

    assert mock_notify.call_args[0][0] == AlertLevel.INFO


def test_log_daily_summary_no_notify_when_no_modifications():
    """Sin modificaciones no se llama notify."""
    log_mock = MagicMock()
    pipeline_result = {
        "status": "ok",
        "ingestion_result": {"status": "ok", "inserted": ["LIC-001"], "modified": []},
        "steps": {},
    }

    with (
        patch("scheduler.run_update.count_licitaciones", return_value=10),
        patch("scheduler.run_update.notify") as mock_notify,
    ):
        from scheduler import run_update

        run_update._log_daily_summary(pipeline_result, log_mock)

    mock_notify.assert_not_called()
