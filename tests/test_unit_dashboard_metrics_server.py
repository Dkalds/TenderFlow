"""Tests unitarios para dashboard.bootstrap.start_metrics_server."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import dashboard.bootstrap as bootstrap_mod


def test_start_metrics_server_idempotent():
    """Segunda llamada retorna True sin re-arrancar el servidor."""
    original = bootstrap_mod._METRICS_SERVER_STARTED
    try:
        bootstrap_mod._METRICS_SERVER_STARTED = True
        assert bootstrap_mod.start_metrics_server(port=19092) is True
    finally:
        bootstrap_mod._METRICS_SERVER_STARTED = original


def test_start_metrics_server_import_error():
    """Si prometheus_client no está disponible, retorna False."""
    original = bootstrap_mod._METRICS_SERVER_STARTED
    try:
        bootstrap_mod._METRICS_SERVER_STARTED = False
        with patch.dict("sys.modules", {"prometheus_client": None}):
            result = bootstrap_mod.start_metrics_server(port=19093)
        assert result is False
    finally:
        bootstrap_mod._METRICS_SERVER_STARTED = original


def test_start_metrics_server_os_error():
    """Si el puerto está ocupado (OSError), retorna False."""
    original = bootstrap_mod._METRICS_SERVER_STARTED
    try:
        bootstrap_mod._METRICS_SERVER_STARTED = False
        mock_mod = MagicMock()
        mock_mod.start_http_server.side_effect = OSError("port in use")
        with patch.dict("sys.modules", {"prometheus_client": mock_mod}):
            # Need to force re-import inside the function
            result = bootstrap_mod.start_metrics_server(port=19094)
        assert result is False
    finally:
        bootstrap_mod._METRICS_SERVER_STARTED = original


def test_start_metrics_server_success():
    """Arranque exitoso retorna True y marca el flag."""
    original = bootstrap_mod._METRICS_SERVER_STARTED
    try:
        bootstrap_mod._METRICS_SERVER_STARTED = False
        mock_mod = MagicMock()
        with patch.dict("sys.modules", {"prometheus_client": mock_mod}):
            result = bootstrap_mod.start_metrics_server(port=19095)
        assert result is True
        assert bootstrap_mod._METRICS_SERVER_STARTED is True
    finally:
        bootstrap_mod._METRICS_SERVER_STARTED = original


def test_prometheus_yml_contains_dashboard_job():
    """El archivo prometheus.yml debe contener el job licitaciones-dashboard."""
    from pathlib import Path

    prom_yml = Path(__file__).parents[1] / "observability" / "prometheus.yml"
    content = prom_yml.read_text()
    assert "licitaciones-dashboard" in content
    assert "dashboard:9092" in content
