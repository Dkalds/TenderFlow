"""Proveedor Anthropic (Claude) para el cliente LLM unificado.

Usa la API de Messages con streaming. Soporta modelos claude-* incluyendo
Claude Sonnet 4.5 (``claude-sonnet-4-5``) y Claude Haiku 4.5
(``claude-haiku-4-5``).

Requiere ``pip install anthropic`` y la variable ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_MAX_TOKENS = 1024
_TEMPERATURE = 0.2


def _build_system_prompt() -> str:
    return (
        "Eres un asistente experto en licitaciones del sector público español. "
        "Responde ÚNICAMENTE con información de los expedientes del contexto proporcionado. "
        "Si el contexto no contiene la respuesta, escribe exactamente: "
        "'No encontrado en el corpus.' "
        "Cita siempre el ID del expediente entre corchetes, ej: [EXP-2024-001]. "
        "Si hay varios expedientes relevantes, incluye una tabla Markdown resumen al final "
        "con columnas: Expediente | Órgano | Importe | Relevancia."
    )


def _build_user_message(question: str, docs: list[dict[str, Any]], keywords: list[str]) -> str:
    def _excerpt(text: str | None, kws: list[str], max_chars: int = 300) -> str:
        if not text:
            return ""
        text = text[: max_chars * 3]
        lower = text.lower()
        for kw in kws:
            pos = lower.find(kw.lower())
            if pos >= 0:
                start = max(0, pos - 60)
                return text[start : start + max_chars]
        return text[:max_chars]

    context = "\n\n".join(
        f"[{d['id_externo']}] {d.get('titulo', '')}\n"
        f"Órgano: {d.get('organo_contratacion', '—')}\n"
        f"Importe: {d.get('importe', '—')}\n"
        f"Estado: {d.get('estado', '—')}\n"
        f"Descripción: {_excerpt(d.get('descripcion'), keywords)}"
        for d in docs
    )
    return f"CONTEXTO:\n{context}\n\nPREGUNTA: {question}"


def stream(
    question: str,
    docs: list[dict[str, Any]],
    model: str,
    keywords: list[str],
    api_key: str,
) -> Iterator[str]:
    """Streaming Anthropic Messages API. Yields string chunks."""
    if not api_key:
        return
    try:
        import anthropic  # type: ignore[import-not-found]

        user_message = _build_user_message(question, docs, keywords)
        log.debug(
            "llm_anthropic.start",
            model=model,
            n_docs=len(docs),
            estimated_tokens=len(user_message) // 4,
        )
        client = anthropic.Anthropic(api_key=api_key)
        with client.messages.stream(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=_build_system_prompt(),
            messages=[{"role": "user", "content": user_message}],
        ) as stream_obj:
            for text in stream_obj.text_stream:
                if text:
                    yield text
    except Exception as exc:
        log.warning("llm_anthropic.failed", model=model, error=str(exc))
