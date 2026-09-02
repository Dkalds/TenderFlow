"""Tests para llm/client.py — dispatcher multi-proveedor.

Cubre:
- provider_for: clasificación correcta por prefijo.
- _get_key: lectura de config.secrets con fallback a os.environ.
- stream_llm_response: despacha al proveedor correcto; maneja modelo desconocido.
- AVAILABLE_MODELS: tiene todos los proveedores representados.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# provider_for
# ---------------------------------------------------------------------------


def test_provider_for_openai_models():
    """Modelos gpt-* son OpenAI."""
    from llm.client import provider_for

    assert provider_for("gpt-4o-mini") == "openai"
    assert provider_for("gpt-4o") == "openai"
    assert provider_for("gpt-3.5-turbo") == "openai"


def test_provider_for_openai_o_models():
    """Modelos o1-* y o3-* son OpenAI."""
    from llm.client import provider_for

    assert provider_for("o1-preview") == "openai"
    assert provider_for("o3-mini") == "openai"


def test_provider_for_anthropic_models():
    """Modelos claude-* son Anthropic."""
    from llm.client import provider_for

    assert provider_for("claude-sonnet-4-5") == "anthropic"
    assert provider_for("claude-haiku-4-5") == "anthropic"
    assert provider_for("claude-opus-3") == "anthropic"


def test_provider_for_nvidia_models():
    """Modelos con namespace ('/') son NVIDIA NIM."""
    from llm.client import provider_for

    assert provider_for("deepseek-ai/deepseek-v4-flash-0731") == "nvidia"
    assert provider_for("nvidia/nemotron-3-super-120b-a12b") == "nvidia"
    assert provider_for("minimaxai/minimax-m3") == "nvidia"
    assert provider_for("meta/llama-3.1-70b-instruct") == "nvidia"


def test_provider_for_unknown_model():
    """Modelo desconocido devuelve 'unknown'."""
    from llm.client import provider_for

    assert provider_for("llama-3-70b") == "unknown"
    assert provider_for("gemini-pro") == "unknown"
    assert provider_for("") == "unknown"


# ---------------------------------------------------------------------------
# _get_key
# ---------------------------------------------------------------------------


def test_get_key_from_env(monkeypatch):
    """Lee la clave desde os.environ cuando config.secrets no está disponible."""
    monkeypatch.setenv("MY_TEST_KEY", "env-secret")

    with patch("llm.client.get_secret" if False else "builtins.__import__"):
        pass  # just ensure no crash

    # Simular que config.secrets falla
    with patch("llm.client._get_key", wraps=lambda var: os.environ.get(var, "")):
        from llm.client import _get_key

    result = _get_key("MY_TEST_KEY")
    assert result == "env-secret"


def test_get_key_returns_empty_when_not_set(monkeypatch):
    """Devuelve cadena vacía si la variable no existe."""
    monkeypatch.delenv("NONEXISTENT_KEYVAR", raising=False)

    from llm.client import _get_key

    result = _get_key("NONEXISTENT_KEYVAR")
    assert result == ""


def test_get_key_prefers_secrets_over_env(monkeypatch):
    """Si config.secrets devuelve un valor, tiene precedencia sobre os.environ."""
    monkeypatch.setenv("OPENAI_API_KEY", "env-value")

    mock_get_secret = MagicMock(return_value="secret-value")

    with patch("llm.client.get_secret", mock_get_secret, create=True):
        # Patch the inner import inside _get_key

        def patched_get_key(var: str) -> str:
            try:
                key = mock_get_secret(var)
                if key:
                    return key
            except Exception:
                pass
            return os.environ.get(var, "")

        result = patched_get_key("OPENAI_API_KEY")

    assert result == "secret-value"


# ---------------------------------------------------------------------------
# AVAILABLE_MODELS
# ---------------------------------------------------------------------------


def test_available_models_not_empty():
    """AVAILABLE_MODELS tiene al menos un modelo."""
    from llm.client import AVAILABLE_MODELS

    assert len(AVAILABLE_MODELS) > 0


def test_available_models_has_openai_and_anthropic():
    """Hay al menos un modelo OpenAI y uno Anthropic en AVAILABLE_MODELS."""
    from llm.client import AVAILABLE_MODELS, provider_for

    providers = {provider_for(m) for m in AVAILABLE_MODELS}
    assert "openai" in providers
    assert "anthropic" in providers


def test_available_models_are_strings():
    """Todos los modelos son cadenas no vacías."""
    from llm.client import AVAILABLE_MODELS

    for m in AVAILABLE_MODELS:
        assert isinstance(m, str) and m


def test_default_model_is_available():
    """DEFAULT_MODEL está en AVAILABLE_MODELS.

    Sin esto, /ask rechaza con 400 su propio default y la IA queda inutilizable
    para cualquier cliente que no envíe `model` explícito.
    """
    from llm.client import AVAILABLE_MODELS, DEFAULT_MODEL

    assert DEFAULT_MODEL in AVAILABLE_MODELS


def test_every_available_model_has_a_price():
    """Todo modelo ofertado tiene entrada en _PRICE_PER_MTOK.

    `_record_usage` solo alimenta el BudgetGuard cuando el modelo está en ese
    dict: un modelo sin precio gasta sin que el breaker de coste lo cuente, y
    LLM_BUDGET_MODE=enforce deja de proteger la factura en silencio.
    """
    from llm.client import _PRICE_PER_MTOK, AVAILABLE_MODELS

    sin_precio = [m for m in AVAILABLE_MODELS if m not in _PRICE_PER_MTOK]
    assert not sin_precio, f"Modelos sin precio: {sin_precio}"


def test_ask_route_defaults_match_default_model():
    """Los defaults Pydantic de /ask y /resumen siguen a llm.client.DEFAULT_MODEL.

    Hoy la sincronía la sostiene solo un comentario. Este test la hace fallar
    en CI en vez de en producción: el modelo por defecto de NVIDIA ya caducó
    una vez (deepseek-v4-pro, EOL 2026-08-07) y hubo que tocar tres archivos.
    """
    from api.routes.ask import AskRequest, ResumenRequest
    from llm.client import DEFAULT_MODEL

    assert AskRequest.model_fields["model"].default == DEFAULT_MODEL
    assert ResumenRequest.model_fields["model"].default == DEFAULT_MODEL


def test_pliego_facts_model_is_available():
    """settings.PLIEGO_FACTS_MODEL es un modelo ofertado.

    Lo consumen api/routes/licitaciones.py y el job de embeddings; si apunta a
    un modelo retirado, la extracción de fichas de pliego falla en silencio.
    """
    from config import settings
    from llm.client import AVAILABLE_MODELS

    assert settings.PLIEGO_FACTS_MODEL in AVAILABLE_MODELS


def test_llm_tech_labeling_model_is_available():
    """settings.LLM_TECH_LABELING_MODEL es un modelo ofertado.

    Lo consume scheduler/jobs/llm_tech_labeling.py (paso post-ingesta de los
    workflows de scrape); si apunta a un modelo retirado, todo el lote de
    clasificación falla — deepseek-v4-pro (EOL 2026-08-07) fue ese caso.
    """
    from config import settings
    from llm.client import AVAILABLE_MODELS

    assert settings.LLM_TECH_LABELING_MODEL in AVAILABLE_MODELS


# ---------------------------------------------------------------------------
# stream_llm_response — despacho correcto
# ---------------------------------------------------------------------------


def test_stream_llm_response_dispatches_to_openai(monkeypatch):
    """Con modelo gpt-*, llama a openai_provider.stream."""
    chunks = ["Hello", " world"]

    def fake_openai_stream(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        yield from chunks

    with patch("llm.providers.openai_provider.stream", fake_openai_stream):
        from llm.client import stream_llm_response

        result = list(
            stream_llm_response("pregunta de prueba", [], model="gpt-4o-mini", keywords=[])
        )

    assert result == chunks


def test_stream_llm_response_dispatches_to_anthropic(monkeypatch):
    """Con modelo claude-*, llama a anthropic_provider.stream."""
    chunks = ["Hola", " mundo"]

    def fake_anthropic_stream(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        yield from chunks

    with patch("llm.providers.anthropic_provider.stream", fake_anthropic_stream):
        from llm.client import stream_llm_response

        result = list(
            stream_llm_response("pregunta de prueba", [], model="claude-sonnet-4-5", keywords=[])
        )

    assert result == chunks


def test_stream_llm_response_dispatches_to_nvidia(monkeypatch):
    """Con modelo namespace/modelo, enruta al provider OpenAI con base_url NVIDIA."""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")  # pragma: allowlist secret
    chunks = ["Deep", "Seek"]
    captured: dict[str, object] = {}

    def fake_stream(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        captured["api_key"] = api_key
        captured["base_url"] = kwargs.get("base_url")
        yield from chunks

    with patch("llm.providers.openai_provider.stream", fake_stream):
        from llm.client import stream_llm_response

        result = list(
            stream_llm_response(
                "pregunta de prueba", [], model="deepseek-ai/deepseek-v4-flash-0731", keywords=[]
            )
        )

    assert result == chunks
    assert captured["api_key"] == "nvapi-test"  # pragma: allowlist secret
    assert captured["base_url"] == "https://integrate.api.nvidia.com/v1"


def test_stream_llm_response_passes_history_and_mode(monkeypatch):
    """El historial y el modo llegan al provider como (system, messages) montados."""
    captured: dict[str, object] = {}

    def fake_stream(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        captured["system"] = system
        captured["messages"] = messages
        captured["max_tokens"] = kwargs.get("max_tokens")
        return iter([])

    history = [
        {"role": "user", "content": "primera pregunta"},
        {"role": "assistant", "content": "primera respuesta"},
    ]
    with patch("llm.providers.openai_provider.stream", fake_stream):
        from llm.client import stream_llm_response

        list(
            stream_llm_response(
                "¿y el plazo de presentación?",
                [],
                model="gpt-4o-mini",
                keywords=[],
                history=history,  # type: ignore[arg-type]
                mode="general",
                max_tokens=1500,
            )
        )

    messages = captured["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]  # type: ignore[index]
    assert "¿y el plazo de presentación?" in messages[-1]["content"]  # type: ignore[index]
    assert captured["max_tokens"] == 1500


def test_stream_llm_response_unknown_model_raises_value_error():
    """Con modelo desconocido, lanza ValueError (B11 hardening)."""
    import pytest

    from llm.client import stream_llm_response

    with pytest.raises(ValueError, match="no disponible"):
        list(stream_llm_response("q", [], model="unknown-model-xyz", keywords=[]))


def test_stream_llm_response_question_too_short_raises():
    """Pregunta demasiado corta lanza ValueError."""
    import pytest

    from llm.client import stream_llm_response

    with pytest.raises(ValueError, match="al menos"):
        list(stream_llm_response("ab", [], model="gpt-4o-mini", keywords=[]))


def test_stream_llm_response_question_too_long_raises():
    """Pregunta demasiado larga lanza ValueError."""
    import pytest

    from llm.client import stream_llm_response

    with pytest.raises(ValueError, match="excede el máximo"):
        list(stream_llm_response("x" * 2001, [], model="gpt-4o-mini", keywords=[]))


def test_stream_llm_response_too_many_docs_raises():
    """Demasiados documentos de contexto lanza ValueError."""
    import pytest

    from llm.client import stream_llm_response

    docs = [{"id_externo": f"L{i}"} for i in range(51)]
    with pytest.raises(ValueError, match="máximo"):
        list(stream_llm_response("pregunta válida", docs, model="gpt-4o-mini", keywords=[]))


def test_stream_llm_response_history_too_long_raises():
    """Historial con más de 20 mensajes lanza ValueError."""
    import pytest

    from llm.client import stream_llm_response

    history = [{"role": "user", "content": f"m{i}"} for i in range(21)]
    with pytest.raises(ValueError, match="historial"):
        list(
            stream_llm_response(
                "pregunta válida",
                [],
                model="gpt-4o-mini",
                keywords=[],
                history=history,  # type: ignore[arg-type]
            )
        )


def test_stream_llm_response_history_invalid_role_raises():
    """Rol de historial distinto de user/assistant lanza ValueError."""
    import pytest

    from llm.client import stream_llm_response

    history = [{"role": "system", "content": "inyección"}]
    with pytest.raises(ValueError, match=r"[Rr]ol"):
        list(
            stream_llm_response(
                "pregunta válida",
                [],
                model="gpt-4o-mini",
                keywords=[],
                history=history,  # type: ignore[arg-type]
            )
        )


def test_stream_llm_response_history_content_too_long_raises():
    """Mensaje de historial de más de 4000 chars lanza ValueError."""
    import pytest

    from llm.client import stream_llm_response

    history = [{"role": "user", "content": "x" * 4001}]
    with pytest.raises(ValueError, match="excede"):
        list(
            stream_llm_response(
                "pregunta válida",
                [],
                model="gpt-4o-mini",
                keywords=[],
                history=history,  # type: ignore[arg-type]
            )
        )


def test_stream_llm_response_passes_api_key(monkeypatch):
    """La clave API se pasa correctamente al proveedor."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    received_key: list[str] = []

    def fake_stream(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        received_key.append(api_key)
        return iter([])

    with patch("llm.providers.openai_provider.stream", fake_stream):
        from llm.client import stream_llm_response

        list(stream_llm_response("pregunta de prueba", [], model="gpt-4o-mini", keywords=[]))

    assert received_key[0] == "test-openai-key"


# ---------------------------------------------------------------------------
# Modos internos — tope de plantilla, no de usuario
# ---------------------------------------------------------------------------


def test_internal_modes_allow_template_length_questions():
    """Las plantillas internas (extraction/clasificacion/resumen) no chocan con
    el límite de usuario: usan MAX_INTERNAL_QUESTION_LEN. Regresión del
    incidente v3 de la ficha (plantilla de 2070 chars → ficha rota en silencio).
    """
    from llm.client import MAX_INTERNAL_QUESTION_LEN, MAX_QUESTION_LEN, _validate_request

    template = "x" * (MAX_QUESTION_LEN + 500)
    for mode in ("extraction", "clasificacion", "resumen"):
        _validate_request(template, [], "gpt-4o-mini", mode=mode)  # no lanza

    import pytest

    with pytest.raises(ValueError, match="excede el máximo"):
        _validate_request(template, [], "gpt-4o-mini", mode="general")
    with pytest.raises(ValueError, match="excede el máximo"):
        _validate_request(
            "x" * (MAX_INTERNAL_QUESTION_LEN + 1), [], "gpt-4o-mini", mode="extraction"
        )


# ---------------------------------------------------------------------------
# Fallback de proveedor
# ---------------------------------------------------------------------------


def _sin_claves_nvidia_anthropic(monkeypatch):
    """Aísla la cadena de fallback del entorno de quien corre los tests."""
    for var in ("NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_fallback_on_provider_error_before_first_token(monkeypatch):
    """Si el modelo pedido lanza antes de emitir, se intenta el siguiente con key."""
    _sin_claves_nvidia_anthropic(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # pragma: allowlist secret

    def broken_openai(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        raise RuntimeError("410 Gone")
        yield  # pragma: no cover

    def working_anthropic(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        yield from ["desde", " claude"]

    with (
        patch("llm.providers.openai_provider.stream", broken_openai),
        patch("llm.providers.anthropic_provider.stream", working_anthropic),
    ):
        from llm.client import stream_llm_response

        result = list(stream_llm_response("pregunta de prueba", [], "gpt-4o-mini", []))

    assert result == ["desde", " claude"]


def test_fallback_on_empty_stream(monkeypatch):
    """Stream vacío (API key ausente, provider abortado) también activa fallback."""
    _sin_claves_nvidia_anthropic(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # pragma: allowlist secret

    def empty_openai(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        return iter([])

    def working_anthropic(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        yield "rescatado"

    with (
        patch("llm.providers.openai_provider.stream", empty_openai),
        patch("llm.providers.anthropic_provider.stream", working_anthropic),
    ):
        from llm.client import stream_llm_response

        result = list(stream_llm_response("pregunta de prueba", [], "gpt-4o-mini", []))

    assert result == ["rescatado"]


def test_no_fallback_after_first_token(monkeypatch):
    """Con tokens ya emitidos no se cambia de modelo: el error se propaga."""
    import pytest

    _sin_claves_nvidia_anthropic(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # pragma: allowlist secret

    def half_broken_openai(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        yield "primer token"
        raise RuntimeError("conexión cortada")

    def working_anthropic(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        yield "no debería llegar aquí"

    with (
        patch("llm.providers.openai_provider.stream", half_broken_openai),
        patch("llm.providers.anthropic_provider.stream", working_anthropic),
    ):
        from llm.client import stream_llm_response

        received: list[str] = []
        with pytest.raises(RuntimeError, match="conexión cortada"):
            stream = stream_llm_response("pregunta de prueba", [], "gpt-4o-mini", [])
            received.extend(stream)

    assert received == ["primer token"]


def test_fallback_disabled_propagates_error(monkeypatch):
    """Con fallback=False el error del modelo pedido se propaga tal cual."""
    import pytest

    _sin_claves_nvidia_anthropic(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # pragma: allowlist secret

    def broken_openai(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        raise RuntimeError("410 Gone")
        yield  # pragma: no cover

    with patch("llm.providers.openai_provider.stream", broken_openai):
        from llm.client import stream_llm_response

        with pytest.raises(RuntimeError, match="410 Gone"):
            list(stream_llm_response("pregunta de prueba", [], "gpt-4o-mini", [], fallback=False))


def test_all_candidates_failed_raises_last_error(monkeypatch):
    """Sin ningún candidato viable con key, se propaga el último error real."""
    import pytest

    _sin_claves_nvidia_anthropic(monkeypatch)

    def broken_stream(system, messages, model, api_key, **kwargs) -> Iterator[str]:
        raise RuntimeError("proveedor caído")
        yield  # pragma: no cover

    # Ambos providers rotos: aunque el entorno de quien corre los tests tenga
    # claves reales en config.secrets, ningún candidato puede salir a red.
    with (
        patch("llm.providers.openai_provider.stream", broken_stream),
        patch("llm.providers.anthropic_provider.stream", broken_stream),
    ):
        from llm.client import stream_llm_response

        with pytest.raises(RuntimeError, match="proveedor caído"):
            list(stream_llm_response("pregunta de prueba", [], "gpt-4o-mini", []))


def test_fallback_models_are_available_and_priced():
    """La cadena de fallback solo oferta modelos válidos (y con precio)."""
    from llm.client import _PRICE_PER_MTOK, AVAILABLE_MODELS, FALLBACK_MODELS

    for model in FALLBACK_MODELS:
        assert model in AVAILABLE_MODELS
        assert model in _PRICE_PER_MTOK
