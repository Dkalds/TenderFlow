"""Tests para observabilidad de tokens y coste LLM (RFC observabilidad-tokens-coste)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_record_usage_increments_counters():
    """_record_usage incrementa tokens y coste cuando prometheus está disponible."""
    from llm.client import _PRICE_PER_MTOK, _record_usage

    mock_tokens = MagicMock()
    mock_cost = MagicMock()

    with (
        patch("llm.client._llm_counters_init", True),
        patch("llm.client._llm_tokens_counter", mock_tokens),
        patch("llm.client._llm_cost_counter", mock_cost),
    ):
        usage = {"input_tokens": 100, "output_tokens": 50, "source": 0}
        _record_usage("gpt-4o-mini", "openai", usage)

    # Tokens counter called for input and output
    calls = mock_tokens.labels.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs == {
        "model": "gpt-4o-mini",
        "provider": "openai",
        "direction": "input",
        "source": "reported",
    }
    assert calls[1].kwargs == {
        "model": "gpt-4o-mini",
        "provider": "openai",
        "direction": "output",
        "source": "reported",
    }
    mock_tokens.labels().inc.assert_called()

    # Cost counter called
    mock_cost.labels.assert_called_once_with(model="gpt-4o-mini", provider="openai")
    price_in, price_out = _PRICE_PER_MTOK["gpt-4o-mini"]
    expected_cost = (100 * price_in + 50 * price_out) / 1_000_000
    mock_cost.labels().inc.assert_called_once_with(expected_cost)


def test_record_usage_estimated_source_label():
    """source=1 se traduce a label 'estimated'."""
    from llm.client import _record_usage

    mock_tokens = MagicMock()

    with (
        patch("llm.client._llm_counters_init", True),
        patch("llm.client._llm_tokens_counter", mock_tokens),
        patch("llm.client._llm_cost_counter", MagicMock()),
    ):
        usage = {"input_tokens": 200, "output_tokens": 0, "source": 1}
        _record_usage("claude-haiku-4-5", "anthropic", usage)

    call = mock_tokens.labels.call_args_list[0]
    assert call.kwargs["source"] == "estimated"


def test_record_usage_unknown_model_no_cost():
    """Modelo sin precio conocido: tokens sí se cuentan, coste no."""
    from llm.client import _record_usage

    mock_tokens = MagicMock()
    mock_cost = MagicMock()

    with (
        patch("llm.client._llm_counters_init", True),
        patch("llm.client._llm_tokens_counter", mock_tokens),
        patch("llm.client._llm_cost_counter", mock_cost),
    ):
        usage = {"input_tokens": 50, "output_tokens": 30, "source": 0}
        _record_usage("unknown-model-xyz", "openai", usage)

    # Tokens sí se registran
    assert mock_tokens.labels.call_count == 2
    # Coste NO se registra (modelo sin precio)
    mock_cost.labels.assert_not_called()


def test_record_usage_empty_dict_noop():
    """Usage vacío no registra nada."""
    from llm.client import _record_usage

    mock_tokens = MagicMock()

    with (
        patch("llm.client._llm_counters_init", True),
        patch("llm.client._llm_tokens_counter", mock_tokens),
        patch("llm.client._llm_cost_counter", MagicMock()),
    ):
        _record_usage("gpt-4o", "openai", {})

    mock_tokens.labels.assert_not_called()


def test_record_usage_no_prometheus():
    """Sin prometheus_client, _record_usage no falla."""
    from llm.client import _record_usage

    with (
        patch("llm.client._llm_counters_init", True),
        patch("llm.client._llm_tokens_counter", None),
        patch("llm.client._llm_cost_counter", None),
    ):
        # No debe lanzar excepción
        _record_usage("gpt-4o", "openai", {"input_tokens": 100, "output_tokens": 50, "source": 0})


def test_anthropic_usage_sink_populated():
    """El proveedor Anthropic rellena usage_sink tras stream exitoso."""
    usage: dict[str, int] = {}

    # Mock del SDK anthropic
    mock_message = MagicMock()
    mock_message.usage.input_tokens = 42
    mock_message.usage.output_tokens = 18

    mock_stream_obj = MagicMock()
    mock_stream_obj.text_stream = iter(["Hello", " world"])
    mock_stream_obj.get_final_message.return_value = mock_message
    mock_stream_obj.__enter__ = MagicMock(return_value=mock_stream_obj)
    mock_stream_obj.__exit__ = MagicMock(return_value=False)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream_obj

    mock_anthropic_mod = MagicMock()
    mock_anthropic_mod.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_mod}):
        from llm.providers.anthropic_provider import stream

        result = list(
            stream(
                "test?",
                [{"id_externo": "X", "titulo": "T"}],
                "claude-haiku-4-5",
                [],
                "key123",
                usage_sink=usage,
            )
        )

    assert result == ["Hello", " world"]
    assert usage["input_tokens"] == 42
    assert usage["output_tokens"] == 18
    assert usage["source"] == 0


def test_openai_usage_sink_populated():
    """El proveedor OpenAI rellena usage_sink del chunk final."""
    usage: dict[str, int] = {}

    # Mock de chunks
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "Hi"

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta.content = " there"

    # Chunk final de usage (choices vacío)
    chunk_usage = MagicMock()
    chunk_usage.choices = []
    chunk_usage.usage = MagicMock()
    chunk_usage.usage.prompt_tokens = 55
    chunk_usage.usage.completion_tokens = 12

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk1, chunk2, chunk_usage])

    mock_openai_mod = MagicMock()
    mock_openai_mod.OpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai_mod}):
        from llm.providers.openai_provider import stream

        result = list(
            stream(
                "test?",
                [{"id_externo": "X", "titulo": "T"}],
                "gpt-4o-mini",
                [],
                "key123",
                usage_sink=usage,
            )
        )

    assert result == ["Hi", " there"]
    assert usage["input_tokens"] == 55
    assert usage["output_tokens"] == 12
    assert usage["source"] == 0


def test_openai_usage_sink_estimation_fallback():
    """Sin chunk de usage del SDK, el provider OpenAI estima y marca source=1."""
    usage: dict[str, int] = {}

    # Único chunk de texto, sin chunk final de usage (proxies/endpoints viejos).
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "abcd"  # 4 chars → 1 token estimado de output

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([chunk1])

    mock_openai_mod = MagicMock()
    mock_openai_mod.OpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai_mod}):
        from llm.providers.openai_provider import stream

        result = list(
            stream(
                "test?",
                [{"id_externo": "X", "titulo": "T"}],
                "gpt-4o-mini",
                [],
                "key123",
                usage_sink=usage,
            )
        )

    assert result == ["abcd"]
    # Fallback de estimación: marcado como estimated, nunca falla la request.
    assert usage["source"] == 1
    assert usage["input_tokens"] > 0  # len(prompt) // 4
    assert usage["output_tokens"] == 1  # 4 chars // 4


def test_partial_consumption_does_not_record_tokens():
    """Si el consumidor abandona el generador antes de agotarlo, no se contabilizan tokens.

    El provider solo puebla ``usage_sink`` al final de su stream; al cerrarse el
    generador a mitad (``GeneratorExit``), el sink queda vacío y ``_record_usage``
    es no-op. Documentado en el RFC como comportamiento aceptable para un contador
    de observabilidad.
    """
    from collections.abc import Iterator

    def fake_stream(
        question: str,
        docs: list,
        model: str,
        keywords: list,
        api_key: str,
        usage_sink: dict | None = None,
        **kwargs: object,
    ) -> Iterator[str]:
        yield "primero"
        yield "segundo"
        # Solo se puebla al final — inalcanzable si se abandona antes.
        if usage_sink is not None:
            usage_sink["input_tokens"] = 100
            usage_sink["output_tokens"] = 50
            usage_sink["source"] = 0

    recorded: list[dict] = []

    def spy_record(model: str, provider: str, usage: dict) -> None:
        recorded.append(dict(usage))

    with (
        patch("llm.providers.openai_provider.stream", fake_stream),
        patch("llm.client._record_usage", spy_record),
    ):
        from llm.client import stream_llm_response

        gen = stream_llm_response("pregunta válida", [], model="gpt-4o-mini", keywords=[])
        first = next(gen)  # consumir solo el primer chunk
        gen.close()  # abandonar antes de agotar

    assert first == "primero"
    # _record_usage corre en el finally, pero con usage vacío (no se pobló).
    assert recorded == [{}]
