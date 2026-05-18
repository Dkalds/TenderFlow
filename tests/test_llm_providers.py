"""Tests for llm/providers/*.py — direct provider coverage."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import llm.providers.anthropic_provider as anth
import llm.providers.openai_provider as oai

# ---------------------------------------------------------------------------
# openai_provider._build_prompt
# ---------------------------------------------------------------------------

DOCS: list[dict[str, Any]] = [
    {
        "id_externo": "EXP-001",
        "titulo": "Obra pública SAP",
        "organo_contratacion": "Ayuntamiento",
        "importe": 100000.0,
        "estado": "VIG",
        "descripcion": "Contrato de implantación de sistema SAP para la gestión.",
    }
]


def test_build_prompt_contains_question() -> None:
    prompt = oai._build_prompt("¿Cuál es el importe?", DOCS, ["SAP"])
    assert "¿Cuál es el importe?" in prompt


def test_build_prompt_contains_doc_id() -> None:
    prompt = oai._build_prompt("pregunta", DOCS, [])
    assert "EXP-001" in prompt


def test_build_prompt_excerpt_with_keyword() -> None:
    docs = [
        {
            "id_externo": "X",
            "descripcion": "contrato sistema SAP para gestión",
            **{k: None for k in ["titulo", "organo_contratacion", "importe", "estado"]},
        }
    ]
    prompt = oai._build_prompt("consulta", docs, ["SAP"])
    assert "SAP" in prompt


def test_build_prompt_excerpt_no_keyword() -> None:
    docs = [
        {
            "id_externo": "X",
            "descripcion": "texto largo " * 50,
            **{k: None for k in ["titulo", "organo_contratacion", "importe", "estado"]},
        }
    ]
    prompt = oai._build_prompt("consulta", docs, ["xyz_no_match"])
    assert "X" in prompt


def test_build_prompt_empty_docs() -> None:
    prompt = oai._build_prompt("pregunta", [], ["kw"])
    assert "pregunta" in prompt
    assert "CONTEXTO" in prompt


def test_build_prompt_none_descripcion() -> None:
    docs = [
        {
            "id_externo": "X",
            "titulo": "T",
            "organo_contratacion": "O",
            "importe": 1.0,
            "estado": "VIG",
            "descripcion": None,
        }
    ]
    prompt = oai._build_prompt("p", docs, [])
    assert "X" in prompt


# ---------------------------------------------------------------------------
# openai_provider.stream — empty api_key
# ---------------------------------------------------------------------------


def test_openai_stream_no_api_key_yields_nothing() -> None:
    result = list(oai.stream("q", DOCS, "gpt-4", [], ""))
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
        result = list(oai.stream("question", DOCS, "gpt-4o", ["kw"], "sk-fake-key"))

    assert "Hello" in result
    assert " world" in result


def test_openai_stream_handles_exception() -> None:
    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI.side_effect = RuntimeError("API error")

    with patch.dict("sys.modules", {"openai": mock_openai_module}):
        result = list(oai.stream("question", DOCS, "gpt-4o", [], "sk-fake-key"))

    assert result == []


def test_openai_stream_import_error_caught() -> None:
    with patch.dict("sys.modules", {"openai": None}):  # type: ignore[dict-item]
        result = list(oai.stream("question", DOCS, "gpt-4o", [], "sk-fake-key"))
    assert result == []


# ---------------------------------------------------------------------------
# anthropic_provider._build_system_prompt
# ---------------------------------------------------------------------------


def test_build_system_prompt_not_empty() -> None:
    result = anth._build_system_prompt()
    assert isinstance(result, str)
    assert len(result) > 10


def test_build_system_prompt_contains_instructions() -> None:
    result = anth._build_system_prompt()
    assert "licitaciones" in result.lower()


# ---------------------------------------------------------------------------
# anthropic_provider._build_user_message
# ---------------------------------------------------------------------------


def test_build_user_message_contains_question() -> None:
    msg = anth._build_user_message("¿Cuánto cuesta?", DOCS, [])
    assert "¿Cuánto cuesta?" in msg


def test_build_user_message_contains_doc_id() -> None:
    msg = anth._build_user_message("q", DOCS, [])
    assert "EXP-001" in msg


def test_build_user_message_excerpt_with_keyword() -> None:
    docs = [
        {
            "id_externo": "X",
            "descripcion": "SAP implantación sistema",
            **{k: None for k in ["titulo", "organo_contratacion", "importe", "estado"]},
        }
    ]
    msg = anth._build_user_message("consulta", docs, ["SAP"])
    assert "SAP" in msg


def test_build_user_message_none_descripcion() -> None:
    docs = [
        {
            "id_externo": "Y",
            "titulo": "T",
            "organo_contratacion": "O",
            "importe": 1.0,
            "estado": "VIG",
            "descripcion": None,
        }
    ]
    msg = anth._build_user_message("p", docs, [])
    assert "Y" in msg


def test_build_user_message_empty_docs() -> None:
    msg = anth._build_user_message("p", [], [])
    assert "PREGUNTA: p" in msg


# ---------------------------------------------------------------------------
# anthropic_provider.stream — empty api_key
# ---------------------------------------------------------------------------


def test_anthropic_stream_no_api_key_yields_nothing() -> None:
    result = list(anth.stream("q", DOCS, "claude-3", [], ""))
    assert result == []


# ---------------------------------------------------------------------------
# anthropic_provider.stream — mocked anthropic client
# ---------------------------------------------------------------------------


def test_anthropic_stream_yields_chunks() -> None:
    # The anthropic client uses a context manager `with client.messages.stream(...) as s:`
    # and iterates `s.text_stream`
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__ = MagicMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_stream_ctx.text_stream = iter(["Hello", " Anthropic"])

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream_ctx

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        result = list(anth.stream("q", DOCS, "claude-sonnet", ["kw"], "ant-fake"))

    assert "Hello" in result
    assert " Anthropic" in result


def test_anthropic_stream_handles_exception() -> None:
    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.side_effect = RuntimeError("Anthropic error")

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        result = list(anth.stream("q", DOCS, "claude-sonnet", [], "ant-fake"))

    assert result == []


def test_anthropic_stream_import_error_caught() -> None:
    with patch.dict("sys.modules", {"anthropic": None}):  # type: ignore[dict-item]
        result = list(anth.stream("q", DOCS, "claude-sonnet", [], "ant-fake"))
    assert result == []


def test_anthropic_stream_skips_empty_text() -> None:
    """Chunks with empty/None text are not yielded."""
    mock_stream_ctx = MagicMock()
    mock_stream_ctx.__enter__ = MagicMock(return_value=mock_stream_ctx)
    mock_stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_stream_ctx.text_stream = iter(["", "real content", ""])

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = mock_stream_ctx

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic.return_value = mock_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
        result = list(anth.stream("q", DOCS, "claude-sonnet", [], "ant-fake"))

    assert result == ["real content"]
