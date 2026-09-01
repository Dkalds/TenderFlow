"""Tests del canary del catálogo NVIDIA NIM (scheduler/jobs/llm_models_canary)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch


def _catalog_response(model_ids: list[str]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"data": [{"id": m} for m in model_ids]}
    return resp


def test_canary_ok_when_all_nim_models_in_catalog():
    from llm.client import AVAILABLE_MODELS, provider_for
    from scheduler.jobs.llm_models_canary import run

    nim = [m for m in AVAILABLE_MODELS if provider_for(m) == "nvidia"]
    with patch("requests.get", return_value=_catalog_response(nim)):
        result = run()

    assert result["checked"] == len(nim)
    assert result["missing"] == []
    assert result["error"] is None


def test_canary_reports_missing_models():
    """Un modelo ofertado que desapareció del catálogo es el hallazgo que este
    job existe para dar: deepseek-v4-pro llegó a EOL sin aviso y devolvió 410
    seis días antes de que nadie lo viera."""
    from llm.client import AVAILABLE_MODELS, provider_for
    from scheduler.jobs.llm_models_canary import run

    nim = [m for m in AVAILABLE_MODELS if provider_for(m) == "nvidia"]
    with patch("requests.get", return_value=_catalog_response(nim[1:])):
        result = run()

    assert result["missing"] == [nim[0]]


def test_canary_network_failure_is_error_not_missing():
    from scheduler.jobs.llm_models_canary import run

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("DNS caído")

    with patch("requests.get", _boom):
        result = run()

    assert result["missing"] == []
    assert "DNS caído" in str(result["error"])
