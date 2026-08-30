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


# ---------------------------------------------------------------------------
# Pasada partida: `--fase ingesta` / `--fase cierre`
#
# `scrape-daily.yml` ejecutaba la secuencia canónica completa —KPIs, refresco de
# la vista pública, evaluación de reglas de vigilancia— y solo entonces lanzaba
# TED, Galicia, Euskadi, adjudicaciones vigiladas, PSCP y TACRC. Cinco de las
# siete fuentes ingerían después de que se calculara todo lo que las incluye.
# Partir la pasada es lo que permite invertir ese orden en el workflow.
# ---------------------------------------------------------------------------


def test_fase_ingesta_no_ejecuta_los_pasos_post_ingesta():
    pipeline_result = {
        "status": "ok",
        "ingestion_result": {"status": "ok", "inserted": [], "modified": []},
        "steps": {},
    }

    with (
        patch("scheduler.run_update.run_daily_pipeline", return_value=pipeline_result) as daily,
        patch("scheduler.run_update.run_post_ingestion_only") as cierre,
        patch("scheduler.run_update.count_licitaciones", return_value=100),
        patch("sys.argv", ["run_update", "--daily", "--fase", "ingesta"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 0
    assert daily.call_args.kwargs["con_cierre"] is False
    cierre.assert_not_called()


def test_fase_cierre_no_ingiere_nada():
    with (
        patch("scheduler.run_update.run_daily_pipeline") as daily,
        patch(
            "scheduler.run_update.run_post_ingestion_only",
            return_value={"status": "ok", "steps": {"kpi_precompute": "ok"}},
        ) as cierre,
        patch("sys.argv", ["run_update", "--daily", "--fase", "cierre"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 0
    daily.assert_not_called()
    cierre.assert_called_once()
    assert cierre.call_args.kwargs["lane"] == "daily"


def test_fase_cierre_pone_el_job_en_rojo_si_un_paso_falla():
    """El cierre es donde viven el refresco de la vista pública y las alertas.

    Un paso roto ahí tiene que verse: es la mitad de la pasada cuyo fallo antes
    quedaba tapado por el exit code de la ingesta.
    """
    with (
        patch(
            "scheduler.run_update.run_post_ingestion_only",
            return_value={
                "status": "degraded",
                "steps": {"kpi_precompute": "ok", "aggregates_precompute": "error"},
            },
        ),
        patch("sys.argv", ["run_update", "--daily", "--fase", "cierre"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 1


def test_por_defecto_la_pasada_sigue_siendo_completa():
    """Ningún caller que no declare fase puede perder el cierre en silencio."""
    pipeline_result = {
        "status": "ok",
        "ingestion_result": {"status": "ok", "inserted": [], "modified": []},
        "steps": {"kpi_precompute": "ok"},
    }

    with (
        patch("scheduler.run_update.run_daily_pipeline", return_value=pipeline_result) as daily,
        patch("scheduler.run_update.count_licitaciones", return_value=100),
        patch("sys.argv", ["run_update", "--daily"]),
    ):
        from scheduler import run_update

        run_update.main()

    assert daily.call_args.kwargs["con_cierre"] is True
