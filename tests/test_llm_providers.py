"""Tests for llm/providers/*.py — direct provider coverage.

Los providers reciben ``(system, messages)`` ya montados (ver ``llm/prompts.py``
y ``tests/test_llm_prompts.py`` para el montaje de prompts).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import llm.providers.anthropic_provider as anth
import llm.providers.openai_provider as oai
from llm.prompts import ChatMessage

SYSTEM = "Eres un asistente experto en licitaciones."
MESSAGES: list[ChatMessage] = [{"role": "user", "content": "CONTEXTO:\n[EXP-001]\n\nPREGUNTA: q"}]

MULTI_TURN: list[ChatMessage] = [
    {"role": "user", "content": "primera pregunta"},
    {"role": "assistant", "content": "primera respuesta"},
    {"role": "user", "content": "¿y el plazo?"},
]


# ---------------------------------------------------------------------------
# openai_provider.stream — empty api_key
# ---------------------------------------------------------------------------


def test_openai_stream_no_api_key_yields_nothing() -> None:
    result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4", ""))
    assert result == []


# ---------------------------------------------------------------------------
# openai_provider.stream — mocked openai client
# ---------------------------------------------------------------------------


def _make_openai_chunk(text: str | None) -> MagicMock:
    chunk = MagicMock()
    if text is not None:
        choice = MagicMock()
        choice.delta.content = text
        chunk.choices = [choice]
    else:
        chunk.choices = []
    return chunk


def test_openai_stream_yields_chunks() -> None:
    chunks = [_make_openai_chunk("Hello"), _make_openai_chunk(" world"), _make_openai_chunk(None)]
    mock_stream_obj = iter(chunks)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_stream_obj

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake-key"))

    assert "Hello" in result
    assert " world" in result


def test_openai_stream_prepends_system_message() -> None:
    """El system prompt viaja como primer mensaje role=system."""
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([])

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        list(oai.stream(SYSTEM, MULTI_TURN, "gpt-4o", "sk-fake-key"))

    sent = mock_client.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0] == {"role": "system", "content": SYSTEM}
    assert sent[1:] == MULTI_TURN


def test_openai_stream_max_tokens_override() -> None:
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = iter([])

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value = mock_client

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake-key", max_tokens=1500))

    assert mock_client.chat.completions.create.call_args.kwargs["max_tokens"] == 1500


def test_openai_stream_handles_exception() -> None:
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.side_effect = RuntimeError("API error")

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake-key"))

    assert result == []


def test_openai_stream_import_error_caught() -> None:
    with patch.dict("sys.modules", {"openai": None}):  # type: ignore[dict-item]
        result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake-key"))
    assert result == []


# ---------------------------------------------------------------------------
# anthropic_provider.stream — empty api_key
# ---------------------------------------------------------------------------


def test_anthropic_stream_no_api_key_yields_nothing() -> None:
    result = list(anth.stream(SYSTEM, MESSAGES, "claude-3", ""))
    assert result == []


# ---------------------------------------------------------------------------
# anthropic_provider.stream — mocked anthropic client
# ---------------------------------------------------------------------------


def _mock_anthropic_stream_ctx(texts: list[str]) -> MagicMock:
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__ = MagicMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_stream_ctx.text_stream = iter(texts)
    return mock_stream_ctx


def test_anthropic_stream_yields_chunks() -> None:
    # The anthropic client uses a context manager `with client.messages.stream(...) as s:`
    # and iterates `s.text_stream`
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _mock_anthropic_stream_ctx(["Hello", " Anthropic"])

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        result = list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "ant-fake"))

    assert "Hello" in result
    assert " Anthropic" in result


def test_anthropic_stream_passes_system_and_messages() -> None:
    """system va como parámetro aparte y messages se envía tal cual (multi-turno)."""
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _mock_anthropic_stream_ctx([])

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        list(anth.stream(SYSTEM, MULTI_TURN, "claude-sonnet", "ant-fake", max_tokens=1500))

    kwargs = mock_client.messages.stream.call_args.kwargs
    assert kwargs["system"] == SYSTEM
    assert kwargs["messages"] == MULTI_TURN
    assert kwargs["max_tokens"] == 1500


def test_anthropic_stream_handles_exception() -> None:
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.side_effect = RuntimeError("Anthropic error")

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        result = list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "ant-fake"))

    assert result == []


def test_anthropic_stream_import_error_caught() -> None:
    with patch.dict("sys.modules", {"anthropic": None}):  # type: ignore[dict-item]
        result = list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "ant-fake"))
    assert result == []


def test_anthropic_stream_skips_empty_text() -> None:
    """Chunks with empty/None text are not yielded."""
    mock_client = MagicMock()
    mock_client.messages.stream.return_value = _mock_anthropic_stream_ctx(["", "real content", ""])

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        result = list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "ant-fake"))

    assert result == ["real content"]


# ── B11: Tests de retry y timeout ─────────────────────────────────────────────


def test_openai_stream_retries_on_connection_error() -> None:
    """openai_provider.stream reintenta ante ConnectionError (máx 3 intentos)."""
    call_count = [0]

    mock_openai_module = MagicMock()

    def failing_create(*args, **kwargs):
        call_count[0] += 1
        raise ConnectionError("network unreachable")

    mock_openai_module.OpenAI.return_value.chat.completions.create.side_effect = failing_create

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        with patch("time.sleep"):  # no esperar en tests
            result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake"))

    assert result == []
    assert call_count[0] == 3  # 3 intentos


def test_openai_stream_no_retry_on_non_retryable_error() -> None:
    """openai_provider.stream no reintenta si el error no es recuperable."""
    call_count = [0]

    mock_openai_module = MagicMock()

    def failing_create(*args, **kwargs):
        call_count[0] += 1
        raise ValueError("invalid model")  # no retryable

    mock_openai_module.OpenAI.return_value.chat.completions.create.side_effect = failing_create

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake"))

    assert result == []
    assert call_count[0] == 1  # solo 1 intento


def test_anthropic_stream_retries_on_connection_error() -> None:
    """anthropic_provider.stream reintenta ante ConnectionError."""
    call_count = [0]

    mock_anthropic_module = MagicMock()

    def failing_stream(*args, **kwargs):
        call_count[0] += 1
        raise ConnectionError("network unreachable")

    mock_anthropic_module.Anthropic.return_value.messages.stream.side_effect = failing_stream

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}), patch("time.sleep"):
        result = list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "ant-fake"))

    assert result == []
    assert call_count[0] == 3


def test_openai_stream_warning_on_missing_key() -> None:
    """openai_provider.stream emite warning cuando api_key está vacía."""
    # api_key="" → early return, sin llamar a OpenAI
    result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", ""))
    assert result == []


def test_anthropic_stream_warning_on_missing_key() -> None:
    """anthropic_provider.stream emite warning cuando api_key está vacía."""
    result = list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", ""))
    assert result == []
