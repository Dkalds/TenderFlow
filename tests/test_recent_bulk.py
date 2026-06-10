"""Tests para scheduler/jobs/recent_bulk.py — orden del pipeline (RFC 086)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def _success_pipeline_mocks():
    """Mocks de las dependencias de recent_bulk.run() con resultado exitoso."""
    return {
        "update_recent": MagicMock(return_value=[{"status": "ok"}, {"status": "ok"}]),
        "run_analytics_export": MagicMock(return_value={"engine": "duckdb-parquet"}),
        "run_kpi_precompute": MagicMock(),
        "run_aggregates_precompute": MagicMock(),
        "check_and_notify": MagicMock(),
    }


def _apply_patches(mocks):
    return [
        patch("scraper.pipeline.update_recent", mocks["update_recent"]),
        patch("db.analytics.run_analytics_export", mocks["run_analytics_export"]),
        patch("scheduler.kpi_precompute.run_kpi_precompute", mocks["run_kpi_precompute"]),
        patch(
            "scheduler.aggregates_precompute.run_aggregates_precompute",
            mocks["run_aggregates_precompute"],
        ),
        patch("scheduler.watchlist_alerts.check_and_notify", mocks["check_and_notify"]),
    ]


def test_run_calls_analytics_export_before_kpi_precompute(_success_pipeline_mocks):
    """run_analytics_export() se invoca antes que run_kpi_precompute()."""
    from scheduler.jobs import recent_bulk

    mocks = _success_pipeline_mocks
    manager = MagicMock()
    manager.attach_mock(mocks["run_analytics_export"], "run_analytics_export")
    manager.attach_mock(mocks["run_kpi_precompute"], "run_kpi_precompute")

    patches = _apply_patches(mocks)
    for p in patches:
        p.start()
    try:
        recent_bulk.run()
    finally:
        for p in patches:
            p.stop()

    call_names = [c[0] for c in manager.mock_calls]
    assert "run_analytics_export" in call_names
    assert "run_kpi_precompute" in call_names
    assert call_names.index("run_analytics_export") < call_names.index("run_kpi_precompute")


def test_run_continues_when_analytics_export_raises(_success_pipeline_mocks):
    """Si run_analytics_export() lanza una excepción, el job sigue y llama run_kpi_precompute()."""
    from scheduler.jobs import recent_bulk

    mocks = _success_pipeline_mocks
    mocks["run_analytics_export"] = MagicMock(side_effect=RuntimeError("boom"))

    patches = _apply_patches(mocks)
    for p in patches:
        p.start()
    try:
        recent_bulk.run()
    finally:
        for p in patches:
            p.stop()

    mocks["run_analytics_export"].assert_called_once()
    mocks["run_kpi_precompute"].assert_called_once()
    mocks["run_aggregates_precompute"].assert_called_once()


def test_run_raises_if_update_recent_fails(_success_pipeline_mocks):
    """Si update_recent() devuelve algún mes con status fallido, run() lanza RuntimeError."""
    from scheduler.jobs import recent_bulk

    mocks = _success_pipeline_mocks
    mocks["update_recent"] = MagicMock(return_value=[{"status": "ok"}, {"status": "error"}])

    patches = _apply_patches(mocks)
    for p in patches:
        p.start()
    try:
        with pytest.raises(RuntimeError):
            recent_bulk.run()
    finally:
        for p in patches:
            p.stop()

    mocks["run_analytics_export"].assert_not_called()
    mocks["run_kpi_precompute"].assert_not_called()


def test_run_accepts_no_publicado_status(_success_pipeline_mocks):
    """status='no_publicado' no se considera un fallo del bulk refresh."""
    from scheduler.jobs import recent_bulk

    mocks = _success_pipeline_mocks
    mocks["update_recent"] = MagicMock(
        return_value=[{"status": "ok"}, {"status": "no_publicado"}]
    )

    patches = _apply_patches(mocks)
    for p in patches:
        p.start()
    try:
        recent_bulk.run()
    finally:
        for p in patches:
            p.stop()

    mocks["run_analytics_export"].assert_called_once()
    mocks["run_kpi_precompute"].assert_called_once()
