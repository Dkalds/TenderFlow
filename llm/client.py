"""Cliente LLM unificado — despacha al proveedor correcto según el modelo.

Interfaz pública:
    stream_llm_response(question, docs, model, keywords) -> Iterator[str]
    available_models() -> list[str]
    provider_for(model) -> str  # "openai" | "anthropic" | "unknown"
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# Mapeo prefijo → proveedor
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-")
_ANTHROPIC_PREFIXES = ("claude-",)

# Modelos mostrados en el selectbox del dashboard
AVAILABLE_MODELS: list[str] = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-3.5-turbo",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]


def provider_for(model: str) -> str:
    """Devuelve el nombre del proveedor para un modelo dado."""
    if any(model.startswith(p) for p in _OPENAI_PREFIXES):
        return "openai"
    if any(model.startswith(p) for p in _ANTHROPIC_PREFIXES):
        return "anthropic"
    return "unknown"


def _get_key(env_var: str) -> str:
    """Lee una clave de config.secrets con fallback a os.environ."""
    try:
        from config.secrets import get_secret

        key = get_secret(env_var)
        if key:
            return key
    except Exception:
        pass
    return os.environ.get(env_var, "")


def stream_llm_response(
    question: str,
    docs: list[dict[str, Any]],
    model: str,
    keywords: list[str],
) -> Iterator[str]:
    """Genera tokens LLM en streaming delegando al proveedor correcto.

    Args:
        question: Pregunta del usuario.
        docs: Lista de dicts con claves ``id_externo``, ``titulo``,
              ``organo_contratacion``, ``importe``, ``estado``, ``descripcion``.
        model: Nombre del modelo (p.ej. ``gpt-4o-mini``, ``claude-sonnet-4-5``).
        keywords: Palabras clave para el extracto contextual.

    Yields:
        Fragmentos de texto del modelo a medida que llegan.
    """
    p = provider_for(model)
    if p == "openai":
        from llm.providers.openai_provider import stream as _stream

        yield from _stream(question, docs, model, keywords, _get_key("OPENAI_API_KEY"))
    elif p == "anthropic":
        from llm.providers.anthropic_provider import stream as _stream

        yield from _stream(question, docs, model, keywords, _get_key("ANTHROPIC_API_KEY"))
    else:
        log.warning("llm_client.unknown_model", model=model)
