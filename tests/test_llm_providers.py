"""Tests for llm/providers/*.py — direct provider coverage.

Los providers reciben ``(system, messages)`` ya montados (ver ``llm/prompts.py``
y ``tests/test_llm_prompts.py`` para el montaje de prompts).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator, Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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


# ── Key rechazada: se lanza, ni se reintenta ni se disfraza de vacío ──────────


class _HTTPStatusError(Exception):
    """Imita los errores de estado de los SDK: solo importa ``status_code``."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"Error code: {status_code}")
        self.status_code = status_code


def test_openai_stream_rejected_key_raises_without_retry() -> None:
    """Un 401 es la key, no la red: reintentar no lo arregla, y el stream vacío
    que devolvía antes escondió la causa seis días (scrape diario, 2026-09)."""
    import pytest

    from llm.providers import LLMAuthError

    call_count = [0]
    mock_openai_module = MagicMock()

    def failing_create(*args, **kwargs):
        call_count[0] += 1
        raise _HTTPStatusError(401)

    mock_openai_module.OpenAI.return_value.chat.completions.create.side_effect = failing_create

    with (
        patch.dict("sys.modules", {"openai": mock_openai_module}),
        patch("time.sleep"),
        pytest.raises(LLMAuthError) as info,
    ):
        list(oai.stream(SYSTEM, MESSAGES, "deepseek-ai/deepseek-v4-flash-0731", "key-rechazada"))

    assert call_count[0] == 1
    assert info.value.status_code == 401
    assert "deepseek-ai/deepseek-v4-flash-0731" in str(info.value)


def test_anthropic_stream_rejected_key_raises_without_retry() -> None:
    import pytest

    from llm.providers import LLMAuthError

    call_count = [0]
    mock_anthropic_module = MagicMock()

    def failing_stream(*args, **kwargs):
        call_count[0] += 1
        raise _HTTPStatusError(403)

    mock_anthropic_module.Anthropic.return_value.messages.stream.side_effect = failing_stream

    with (
        patch.dict("sys.modules", {"anthropic": mock_anthropic_module}),
        patch("time.sleep"),
        pytest.raises(LLMAuthError),
    ):
        list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "key-rechazada"))

    assert call_count[0] == 1


# ── Una sola capa de retry: el SDK no reintenta por dentro ────────────────────
#
# El provider ya tiene su bucle de 3 intentos con backoff. Con el default del
# SDK (`max_retries=2`) cada intento del provider eran hasta 3 peticiones HTTP
# de 30 s: en producción (2026-09-05/06) `llm_openai.retry` salía cada ~92 s y
# `llm_openai.failed` llegaba a los ~4,5 min — 9 peticiones por pregunta.


@pytest.mark.parametrize("base_url", [None, "https://integrate.api.nvidia.com/v1"])
def test_openai_client_disables_sdk_retries(base_url: str | None) -> None:
    """Cada intento del provider crea el cliente con ``max_retries=0`` (OpenAI y NIM)."""
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value.chat.completions.create.side_effect = ConnectionError(
        "network unreachable"
    )

    with patch.dict("sys.modules", {"openai": mock_openai_module}), patch("time.sleep"):
        list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake", base_url=base_url))

    calls = mock_openai_module.OpenAI.call_args_list
    assert [c.kwargs["max_retries"] for c in calls] == [0, 0, 0]
    assert all(c.kwargs["timeout"] == oai._REQUEST_TIMEOUT for c in calls)
    assert all(c.kwargs["base_url"] == base_url for c in calls)


def test_anthropic_client_disables_sdk_retries() -> None:
    """Cada intento del provider crea el cliente con ``max_retries=0``."""
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value.messages.stream.side_effect = ConnectionError(
        "network unreachable"
    )

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}), patch("time.sleep"):
        list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "ant-fake"))

    calls = mock_anthropic_module.Anthropic.call_args_list
    assert [c.kwargs["max_retries"] for c in calls] == [0, 0, 0]
    assert all(c.kwargs["timeout"] == anth._REQUEST_TIMEOUT for c in calls)


def test_openai_sdk_timeout_is_one_http_request_per_attempt() -> None:
    """Con el SDK real, un timeout persistente son 3 peticiones HTTP, no 9.

    Es el incidente de producción reproducido de punta a punta: el transporte
    lanza ``httpx.ReadTimeout`` y el SDK lo convierte en ``APITimeoutError``
    ("Request timed out."). Si una versión futura del SDK renombra o ignora
    ``max_retries``, este test lo detecta; el de arriba, con el SDK mockeado, no.
    """
    openai = pytest.importorskip("openai")
    import httpx

    seen: list[httpx.Request] = []

    def _always_timeout(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    real_client_cls = openai.OpenAI

    def _client_with_mock_transport(**kwargs: Any) -> Any:
        transport = httpx.MockTransport(_always_timeout)
        return real_client_cls(**kwargs, http_client=httpx.Client(transport=transport))

    with patch.object(openai, "OpenAI", _client_with_mock_transport), patch("time.sleep"):
        result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake-key"))

    assert result == []
    assert len(seen) == 3


@pytest.mark.parametrize("provider", [oai, anth], ids=["openai", "anthropic"])
def test_http_408_is_retryable(provider: Any) -> None:
    """El 408 lo reintentaba el SDK; con ``max_retries=0`` lo cubre el provider.

    Ninguno de los dos SDK tiene subclase para el 408 (llega como
    ``APIStatusError`` genérico), así que solo se reconoce por el código.
    """
    assert provider._is_retryable(_HTTPStatusError(408))


# ── Señal de parada (stop) ────────────────────────────────────────────────────
#
# `/ask` la activa al vencer su timeout o desconectarse el cliente. La lectura
# HTTP en curso no se puede interrumpir, pero después de ella no se abre ningún
# intento más: cada uno es gasto de presupuesto en una respuesta sin lector.


class _FakeOpenAIStream:
    """``Stream`` del SDK: cuenta los chunks leídos y registra ``close()``."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = texts
        self.leidos = 0
        self.cerrado = False

    def __iter__(self) -> Iterator[MagicMock]:
        for text in self._texts:
            self.leidos += 1
            yield _make_openai_chunk(text)

    def close(self) -> None:
        self.cerrado = True


def test_openai_stream_no_retry_after_stop() -> None:
    """La parada llega durante un intento que falla: no hay un segundo intento."""
    stop = threading.Event()
    call_count = [0]

    def failing_create(*_args: object, **_kwargs: object) -> None:
        call_count[0] += 1
        stop.set()  # el timeout de /ask vence mientras dura esta lectura
        raise ConnectionError("read timeout")

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value.chat.completions.create.side_effect = failing_create

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake", stop=stop))

    assert result == []
    assert call_count[0] == 1


def test_openai_stream_stop_already_set_makes_no_request() -> None:
    stop = threading.Event()
    stop.set()
    mock_openai_module = MagicMock()

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake", stop=stop))

    assert result == []
    mock_openai_module.OpenAI.return_value.chat.completions.create.assert_not_called()


def test_openai_backoff_is_cut_short_by_stop() -> None:
    """La espera de backoff (1 s) no retiene el hilo: la parada la despierta."""
    stop = threading.Event()
    call_count = [0]

    def failing_create(*_args: object, **_kwargs: object) -> None:
        call_count[0] += 1
        # La parada llega DURANTE el backoff, no antes de empezarlo.
        threading.Timer(0.05, stop.set).start()
        raise ConnectionError("network unreachable")

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value.chat.completions.create.side_effect = failing_create

    t0 = time.monotonic()
    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        result = list(oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake", stop=stop))
    elapsed = time.monotonic() - t0

    assert result == []
    assert call_count[0] == 1
    assert elapsed < 0.9


def test_openai_stream_closed_mid_response_closes_http_and_estimates_usage() -> None:
    """Cerrar el generador a mitad cierra el stream del SDK y deja uso estimado.

    El SDK solo reporta el uso en el último chunk: sin la estimación, lo ya
    generado (y facturado) no llegaría al presupuesto.
    """
    fake_stream = _FakeOpenAIStream(["Hola ", "mundo ", "sin ", "leer"])
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.return_value.chat.completions.create.return_value = fake_stream
    usage: dict[str, int] = {}

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        gen = oai.stream(SYSTEM, MESSAGES, "gpt-4o", "sk-fake", usage_sink=usage)
        assert isinstance(gen, Generator)
        assert next(gen) == "Hola "
        gen.close()

    assert fake_stream.cerrado
    assert fake_stream.leidos == 1
    assert usage["source"] == 1
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] == len("Hola ") // 4


def test_anthropic_stream_no_retry_after_stop() -> None:
    stop = threading.Event()
    call_count = [0]

    def failing_stream(*_args: object, **_kwargs: object) -> None:
        call_count[0] += 1
        stop.set()
        raise ConnectionError("read timeout")

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value.messages.stream.side_effect = failing_stream

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        result = list(anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "ant-fake", stop=stop))

    assert result == []
    assert call_count[0] == 1


def test_anthropic_stream_closed_mid_response_exits_context_and_estimates_usage() -> None:
    ctx = _mock_anthropic_stream_ctx(["Hola mundo ", "sin leer"])
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value.messages.stream.return_value = ctx
    usage: dict[str, int] = {}

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        gen = anth.stream(SYSTEM, MESSAGES, "claude-sonnet", "ant-fake", usage_sink=usage)
        assert isinstance(gen, Generator)
        assert next(gen) == "Hola mundo "
        gen.close()

    ctx.__exit__.assert_called_once()  # el `with` del SDK cierra la respuesta HTTP
    ctx.get_final_message.assert_not_called()
    assert usage == {
        "input_tokens": (len(SYSTEM) + len(MESSAGES[0]["content"])) // 4,
        "output_tokens": len("Hola mundo ") // 4,
        "source": 1,
    }
