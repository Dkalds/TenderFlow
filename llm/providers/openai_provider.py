"""Proveedor OpenAI para el cliente LLM unificado."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)


def _build_prompt(question: str, docs: list[dict[str, Any]], keywords: list[str]) -> str:
    """Construye el prompt RAG estándar."""

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
    return (
        "Eres un asistente experto en licitaciones del sector público español. "
        "Responde ÚNICAMENTE con información de los expedientes del contexto. "
        "Si el contexto no contiene la respuesta, escribe exactamente: "
        "'No encontrado en el corpus.' "
        "Cita siempre el ID del expediente entre corchetes, ej: [EXP-2024-001]. "
        "Si hay varios expedientes relevantes, incluye una tabla Markdown resumen al final "
        "con columnas: Expediente | Órgano | Importe | Relevancia.\n\n"
        f"CONTEXTO:\n{context}\n\n"
        f"PREGUNTA: {question}"
    )


def stream(
    question: str,
    docs: list[dict[str, Any]],
    model: str,
    keywords: list[str],
    api_key: str,
) -> Iterator[str]:
    """Streaming OpenAI. Yields string chunks."""
    if not api_key:
        return
    try:
        from openai import OpenAI  # type: ignore[import-not-found]

        prompt = _build_prompt(question, docs, keywords)
        log.debug(
            "llm_openai.start",
            model=model,
            n_docs=len(docs),
            estimated_tokens=len(prompt) // 4,
        )
        client = OpenAI(api_key=api_key)
        stream_obj = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            temperature=0.2,
            stream=True,
        )
        for chunk in stream_obj:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as exc:
        log.warning("llm_openai.failed", model=model, error=str(exc))
