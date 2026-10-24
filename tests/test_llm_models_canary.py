"""Tests del canary del catálogo NVIDIA NIM (scheduler/jobs/llm_models_canary)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from llm.budget import BudgetGuard
from llm.providers import LLMAuthError, LLMModelUnavailableError

_OPENAI_STREAM = "llm.providers.openai_provider.stream"


@pytest.fixture(autouse=True)
def _sin_key_por_defecto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin key el canary se queda en el catálogo: ningún test abre una
    petición de chat salvo que lo pida (``_con_key``)."""
    monkeypatch.setattr("llm.client.provider_key_available", lambda provider: False)


@pytest.fixture
def _con_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("llm.client.provider_key_available", lambda provider: True)


def _catalog_response(model_ids: list[str]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"data": [{"id": m} for m in model_ids]}
    return resp


def _nim_models() -> list[str]:
    from llm.client import AVAILABLE_MODELS, provider_for

    return [m for m in AVAILABLE_MODELS if provider_for(m) == "nvidia"]


def _chat_ok(calls: list[dict[str, Any]] | None = None) -> Any:
    """Transporte simulado de un NIM que sirve el modelo y reporta su uso."""

    def _stream(
        system: str, messages: list[Any], model: str, api_key: str, **kwargs: Any
    ) -> Iterator[str]:
        if calls is not None:
            calls.append({"model": model, **kwargs})
        usage = kwargs.get("usage_sink")
        if usage is not None:
            usage.update({"input_tokens": 1000, "output_tokens": 2, "source": 0})
        yield "ok"

    return _stream


def _chat_raises(exc: Exception) -> Any:
    def _stream(*args: Any, **kwargs: Any) -> Iterator[str]:
        raise exc
        yield ""  # pragma: no cover - hace de esto un generador

    return _stream


def _chat_empty(*args: Any, **kwargs: Any) -> Iterator[str]:
    """Lo que devuelve el provider tras agotar reintentos por timeout o 5xx."""
    return iter(())


def test_canary_ok_when_all_nim_models_in_catalog():
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
    with patch("requests.get", return_value=_catalog_response(nim)):
        result = run()

    assert result["checked"] == len(nim)
    assert result["missing"] == []
    assert result["error"] is None


def test_canary_reports_missing_models():
    """Un modelo ofertado que desapareció del catálogo es el hallazgo que este
    job existe para dar: deepseek-v4-pro llegó a EOL sin aviso y devolvió 410
    seis días antes de que nadie lo viera."""
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
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


def test_canary_sin_key_se_queda_en_el_catalogo():
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
    with (
        patch("requests.get", return_value=_catalog_response(nim)),
        patch(_OPENAI_STREAM, _chat_raises(AssertionError("no debe llamar al chat"))),
    ):
        result = run()

    assert result["chat_skipped"] == "no_key"
    assert result["chat_checked"] == 0
    assert result["missing"] == []


def test_canary_catalogo_ok_y_chat_ok(_con_key: None):
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
    calls: list[dict[str, Any]] = []
    with (
        patch("requests.get", return_value=_catalog_response(nim)),
        patch(_OPENAI_STREAM, _chat_ok(calls)),
    ):
        result = run()

    assert result["missing"] == []
    assert result["unserved"] == []
    assert result["unverified"] == []
    assert result["chat_skipped"] is None
    assert result["chat_checked"] == len(nim)
    assert [c["model"] for c in calls] == nim
    # Petición mínima y sin traza de razonamiento (registro del cliente).
    assert all(c["max_tokens"] <= 16 for c in calls)
    assert all(c["chat_template_kwargs"] == {"thinking": False} for c in calls)


def test_canary_modelo_listado_con_chat_404_falla_nombrandolo(_con_key: None):
    """El incidente del 2026-10-20: ``nemotron-3-super`` seguía en el catálogo
    y el chat daba 404; el canary dio ``llm_models_canary_ok``."""
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
    exc = LLMModelUnavailableError(model=nim[0], status_code=404)
    with (
        patch("requests.get", return_value=_catalog_response(nim)),
        patch(_OPENAI_STREAM, _chat_raises(exc)),
        patch("scheduler.jobs.llm_models_canary.log") as log,
    ):
        result = run()

    assert result["missing"] == [nim[0]]
    assert result["unserved"] == [nim[0]]
    final = log.error.call_args_list[-1]
    assert final.args[0] == "llm_models_canary_models_missing"
    assert final.kwargs["models"] == [nim[0]]
    assert all(c.args[0] != "llm_models_canary_ok" for c in log.info.call_args_list)


def test_canary_chat_410_cuenta_igual_que_404(_con_key: None):
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
    exc = LLMModelUnavailableError(model=nim[0], status_code=410)
    with (
        patch("requests.get", return_value=_catalog_response(nim)),
        patch(_OPENAI_STREAM, _chat_raises(exc)),
    ):
        result = run()

    assert result["unserved"] == [nim[0]]


def test_canary_stream_vacio_es_inconcluso_no_ausente(_con_key: None):
    """Timeout o 5xx tras los reintentos del provider: stream vacío. No es un
    modelo retirado, y no tumba el paso, pero se reporta aparte."""
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
    with (
        patch("requests.get", return_value=_catalog_response(nim)),
        patch(_OPENAI_STREAM, _chat_empty),
    ):
        result = run()

    assert result["missing"] == []
    assert result["unserved"] == []
    assert result["unverified"] == nim


def test_canary_key_rechazada_no_marca_modelos_ausentes(_con_key: None):
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
    exc = LLMAuthError(model=nim[0], status_code=401)
    with (
        patch("requests.get", return_value=_catalog_response(nim)),
        patch(_OPENAI_STREAM, _chat_raises(exc)),
    ):
        result = run()

    assert result["chat_skipped"] == "auth_rejected"
    assert result["missing"] == []


def test_canary_modelo_ausente_del_catalogo_no_gasta_chat(_con_key: None):
    from scheduler.jobs.llm_models_canary import run

    nim = _nim_models()
    calls: list[dict[str, Any]] = []
    with (
        patch("requests.get", return_value=_catalog_response(nim[1:])),
        patch(_OPENAI_STREAM, _chat_ok(calls)),
    ):
        result = run()

    assert result["missing"] == [nim[0]]
    assert nim[0] not in [c["model"] for c in calls]


def test_canary_respeta_el_presupuesto_en_enforce(_con_key: None):
    """Con el tope agotado en ``enforce`` no se abre ninguna petición, y el
    canary no lo toma por un modelo ausente."""
    from scheduler.jobs.llm_models_canary import run

    guard = BudgetGuard(daily_limit_usd=1.0, monthly_limit_usd=100.0, mode="enforce")
    guard.record(5.0)
    nim = _nim_models()
    calls: list[dict[str, Any]] = []
    with (
        patch("llm.budget.get_budget_guard", return_value=guard),
        patch("requests.get", return_value=_catalog_response(nim)),
        patch(_OPENAI_STREAM, _chat_ok(calls)),
    ):
        result = run()

    assert calls == []
    assert result["chat_skipped"] == "budget"
    assert result["missing"] == []


def test_canary_el_chat_suma_al_gasto_del_guard(_con_key: None):
    from scheduler.jobs.llm_models_canary import run

    guard = BudgetGuard(daily_limit_usd=100.0, monthly_limit_usd=1000.0, mode="enforce")
    nim = _nim_models()
    with (
        patch("llm.budget.get_budget_guard", return_value=guard),
        patch("requests.get", return_value=_catalog_response(nim)),
        patch(_OPENAI_STREAM, _chat_ok()),
    ):
        run()

    assert guard.spent("daily") > 0
