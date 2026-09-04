"""Tests para scheduler/jobs/recent_bulk.py — pipeline canónica (ADR-012)."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


def _resultados_por_mes(results: list[dict[str, Any]]):
    """``side_effect`` para ``run_connector``: un resultado por mes esperado.

    Traduce el shape que devolvían los tests del camino legacy
    (``[{"year": ..., "status": "ok"|"error_descarga"}]``) al
    ``ConnectorRunResult`` que consume el bucle nuevo: lo único que decide el
    estado del mes es ``fetch_failed``.
    """
    pendientes = list(results)

    def _side_effect(connector: Any, **_: Any) -> SimpleNamespace:
        esperado = pendientes.pop(0)
        return SimpleNamespace(
            source_id=connector.source_id,
            fetch_failed=esperado["status"] != "ok",
            fetched=0,
            parsed=0,
            nuevas=esperado.get("nuevas", 0),
            actualizadas=esperado.get("actualizadas", 0),
            adjudicaciones=0,
            errores=0,
        )

    return _side_effect


def test_run_calls_analytics_export_before_kpi_precompute():
    """run_bulk_pipeline ejecuta analytics export antes que KPI precompute."""
    from scheduler.jobs import recent_bulk

    called: list[str] = []

    def mock_bulk_pipeline(months: int) -> dict:
        called.append(f"run_bulk_pipeline({months})")
        return {"status": "ok", "ingestion_results": [], "steps": {}}

    with patch("scheduler.pipeline_runs.run_bulk_pipeline", side_effect=mock_bulk_pipeline):
        recent_bulk.run()

    assert len(called) == 1
    assert "run_bulk_pipeline(3)" in called[0]


def test_run_continues_when_analytics_export_raises():
    """Si un paso post-ingesta falla, la pipeline canónica continúa."""
    from scheduler.pipeline_runs import _run_post_ingestion_steps

    with (
        patch(
            "scheduler.pipeline_runs._run_analytics_export",
            side_effect=RuntimeError("boom"),
        ),
        patch("scheduler.pipeline_runs._run_ml_scoring"),
        patch("scheduler.pipeline_runs._run_ml_tecnologias"),
        patch("scheduler.pipeline_runs._run_tech_signal_merge"),
        patch("scheduler.pipeline_runs._run_kpi_precompute"),
        patch("scheduler.pipeline_runs._run_aggregates_precompute"),
        patch("scheduler.pipeline_runs._run_watchlist_notify"),
        patch("scheduler.pipeline_runs._run_dlq_retry"),
        patch("scheduler.pipeline_runs._run_anomaly_checks"),
    ):
        results = _run_post_ingestion_steps()

    assert results["analytics_export"] == "error"
    assert results["kpi_precompute"] == "ok"


def test_run_raises_if_update_recent_fails():
    """Si la ingesta falla, run_bulk_pipeline lanza RuntimeError."""
    from scheduler.jobs import recent_bulk

    with patch(
        "scheduler.pipeline_runs.run_bulk_pipeline",
        side_effect=RuntimeError("bulk failed"),
    ):
        with pytest.raises(RuntimeError):
            recent_bulk.run()


def test_run_accepts_no_publicado_status():
    """status='no_publicado' no se considera un fallo del bulk refresh."""
    from scheduler.jobs import recent_bulk

    result = {
        "status": "ok",
        "ingestion_results": [{"status": "ok"}, {"status": "no_publicado"}],
        "steps": {},
    }

    with patch("scheduler.pipeline_runs.run_bulk_pipeline", return_value=result):
        recent_bulk.run()  # Should not raise


def test_partial_failure_runs_post_ingestion_and_reports_degraded():
    """Un mes fallido no aborta la pipeline: corre post-ingesta y reporta degraded."""
    from scheduler.pipeline_runs import run_bulk_pipeline

    results = [
        {"year": 2026, "month": 5, "status": "ok", "nuevas": 3, "actualizadas": 1},
        {"year": 2026, "month": 6, "status": "error_descarga"},
    ]

    with (
        patch("scheduler.pipeline_runs.meses_a_procesar", return_value=[(2026, 5), (2026, 6)]),
        patch("scraper.connectors.base.run_connector", side_effect=_resultados_por_mes(results)),
        patch("db.database.log_extraccion"),
        patch("observability.bind_run_context", return_value="run-test"),
        patch("observability.record_run", return_value=nullcontext(MagicMock())),
        patch("scraper.pipeline._summarize"),
        patch(
            "scheduler.pipeline_runs._run_post_ingestion_steps",
            return_value={"dlq_retry": "ok"},
        ) as mock_steps,
        patch("scheduler.pipeline_runs._notify_degraded") as mock_notify,
    ):
        out = run_bulk_pipeline(months=2)

    mock_steps.assert_called_once()  # dlq_retry etc. sí corren
    mock_notify.assert_called_once()
    assert out["status"] == "degraded"
    assert [(r["year"], r["month"]) for r in out["failed_months"]] == [(2026, 6)]


def test_total_failure_raises_runtimeerror():
    """Si fallan todos los meses, se lanza RuntimeError (fatal genuino)."""
    from scheduler.pipeline_runs import run_bulk_pipeline

    results = [
        {"year": 2026, "month": 5, "status": "error_descarga"},
        {"year": 2026, "month": 6, "status": "error_descarga"},
    ]

    with (
        patch("scheduler.pipeline_runs.meses_a_procesar", return_value=[(2026, 5), (2026, 6)]),
        patch("scraper.connectors.base.run_connector", side_effect=_resultados_por_mes(results)),
        patch("db.database.log_extraccion"),
        patch("observability.bind_run_context", return_value="run-test"),
        patch("observability.record_run", return_value=nullcontext(MagicMock())),
        patch("scraper.pipeline._summarize"),
        patch("scheduler.pipeline_runs._run_post_ingestion_steps") as mock_steps,
    ):
        with pytest.raises(RuntimeError, match="all 2 month"):
            run_bulk_pipeline(months=2)

    mock_steps.assert_not_called()  # no hay nada que post-procesar


def test_run_update_returns_1_on_degraded():
    """run_update.main devuelve 1 (no fatal) cuando el bulk queda degradado."""
    pipeline_result = {
        "status": "degraded",
        "ingestion_results": [{"status": "ok", "nuevas": 1, "actualizadas": 0}],
        "failed_months": [{"year": 2026, "month": 6, "status": "error_descarga"}],
        "steps": {"dlq_retry": "ok"},
    }

    with (
        patch("scheduler.run_update.run_bulk_pipeline", return_value=pipeline_result),
        patch("scheduler.run_update.count_licitaciones", return_value=200),
        patch("scheduler.run_update.notify") as mock_notify,
        patch("sys.argv", ["run_update"]),
    ):
        from scheduler import run_update

        code = run_update.main()

    assert code == 1
    mock_notify.assert_not_called()  # sin alerta CRITICAL "error fatal"


# ── El job `recent_bulk` sobre el carril bulk ────────────────────────────────
# Hasta 2026-09 estos tests ejercitaban `scraper.pipeline.update_recent` (el
# camino legacy que gobernaba `PLACSP_CONNECTOR_ENABLED=False`). Esa rama se
# retiró con `process_month` (S2.1): `run_bulk_pipeline` va siempre por el
# conector, así que el punto de intercepción es el bucle por meses.


class TestRunRecentBulk:
    @patch("scheduler.pipeline_runs._run_bulk_pipeline_connector", return_value={"status": "ok"})
    def test_success(self, bucle: MagicMock) -> None:
        from scheduler.jobs.recent_bulk import run

        run()

        bucle.assert_called_once_with(3)

    def test_failure(self) -> None:
        """Si fallan todos los meses, el fallo llega hasta el caller del job."""
        from scheduler.jobs.recent_bulk import run

        with (
            patch("scheduler.pipeline_runs.meses_a_procesar", return_value=[(2026, 5)]),
            patch(
                "scraper.connectors.base.run_connector",
                side_effect=_resultados_por_mes([{"year": 2026, "month": 5, "status": "error"}]),
            ),
            patch("db.database.log_extraccion"),
            patch("observability.bind_run_context", return_value="run-test"),
            patch("observability.record_run", return_value=nullcontext(MagicMock())),
            patch("scraper.pipeline._summarize"),
            pytest.raises(RuntimeError, match="bulk refresh"),
        ):
            run()


class TestRunRecentBulkDefault:
    @patch("scheduler.pipeline_runs._run_bulk_pipeline_connector", return_value={"status": "ok"})
    def test_reads_env(self, bucle: MagicMock) -> None:
        with patch.dict("os.environ", {"SCHEDULER_BULK_MONTHS": "5"}):
            from scheduler.jobs.recent_bulk import run

            run()
        bucle.assert_called_once_with(5)
