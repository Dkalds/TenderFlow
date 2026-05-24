"""Proveedor Anthropic (Claude) para el cliente LLM unificado.

Usa la API de Messages con streaming. Soporta modelos claude-* incluyendo
Claude Sonnet 4.5 (``claude-sonnet-4-5``) y Claude Haiku 4.5
(``claude-haiku-4-5``).

Requiere ``pip install anthropic`` y la variable ``ANTHROPIC_API_KEY``.

Hardening (B11):
    - Timeout de 30 s en la llamada a la API.
    - Retry automático (3 intentos, backoff exponencial) ante errores transitorios.
    - Log de API key missing como warning en vez de silencio.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

_MAX_TOKENS = 1024
_TEMPERATURE = 0.2
_REQUEST_TIMEOUT = 30.0

_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


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


def _is_retryable(exc: Exception) -> bool:
    """Determina si la excepción amerita un retry."""
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    code = getattr(exc, "status_code", None)
    if code in _RETRYABLE_HTTP_CODES:
        return True
    name = type(exc).__name__.lower()
    return any(k in name for k in ("ratelimit", "timeout", "connection", "overload"))


def stream(
    question: str,
    docs: list[dict[str, Any]],
    model: str,
    keywords: list[str],
    api_key: str,
) -> Iterator[str]:
    """Streaming Anthropic Messages API con retry y timeout.

    Args:
        question: Pregunta del usuario.
        docs: Documentos de contexto.
        model: Nombre del modelo Anthropic.
        keywords: Palabras clave para excerpts.
        api_key: Clave de API de Anthropic.

    Yields:
        Fragmentos de texto del modelo.
    """
    if not api_key:
        log.warning("llm_anthropic.api_key_missing", model=model)
        return

    try:
        import anthropic  # type: ignore[import-not-found]
    except ImportError:
        log.warning("llm_anthropic.package_not_installed", hint="pip install anthropic")
        return

    user_message = _build_user_message(question, docs, keywords)
    log.debug(
        "llm_anthropic.start",
        model=model,
        n_docs=len(docs),
        estimated_tokens=len(user_message) // 4,
    )

    max_attempts = 3
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            client = anthropic.Anthropic(
                api_key=api_key,
                timeout=_REQUEST_TIMEOUT,
            )
            with client.messages.stream(
                model=model,
                max_tokens=_MAX_TOKENS,
                system=_build_system_prompt(),
                messages=[{"role": "user", "content": user_message}],
            ) as stream_obj:
                for text in stream_obj.text_stream:
                    if text:
                        yield text
            return  # éxito
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts and _is_retryable(exc):
                import time

                wait = 2 ** (attempt - 1)
                log.warning(
                    "llm_anthropic.retry",
                    model=model,
                    attempt=attempt,
                    wait_s=wait,
                    error=str(exc),
                )
                time.sleep(wait)
            else:
                break

    log.warning(
        "llm_anthropic.failed",
        model=model,
        attempts=max_attempts,
        error=str(last_exc),
    )
