"""Proveedor OpenAI para el cliente LLM unificado.

Hardening (B11):
    - Timeout de 30 s en la llamada a la API.
    - Retry automático (3 intentos, backoff exponencial) ante errores transitorios
      (``ConnectionError``, ``TimeoutError``, errores HTTP 429/500/502/503).
    - Log de tokens estimados pre-request y error detallado post-failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# Timeout en segundos para la llamada a la API de OpenAI
_REQUEST_TIMEOUT = 30.0
# Máximo de tokens generados por respuesta
_MAX_TOKENS = 900
_TEMPERATURE = 0.2

# Errores HTTP de OpenAI que ameritan retry
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


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


def _is_retryable(exc: Exception) -> bool:
    """Determina si la excepción amerita un retry."""
    name = type(exc).__name__.lower()
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    # openai.APIStatusError / httpx errors por código
    code = getattr(exc, "status_code", None)
    if code in _RETRYABLE_HTTP_CODES:
        return True
    # Nombres comunes de excepciones transitorias de openai-python
    return any(k in name for k in ("ratelimit", "timeout", "connection", "apiconnection"))


def stream(
    question: str,
    docs: list[dict[str, Any]],
    model: str,
    keywords: list[str],
    api_key: str,
) -> Iterator[str]:
    """Streaming OpenAI con retry y timeout.

    Args:
        question: Pregunta del usuario.
        docs: Documentos de contexto.
        model: Nombre del modelo OpenAI.
        keywords: Palabras clave para excerpts.
        api_key: Clave de API de OpenAI.

    Yields:
        Fragmentos de texto del modelo.
    """
    if not api_key:
        log.warning("llm_openai.api_key_missing", model=model)
        return

    try:
        from openai import OpenAI  # type: ignore[import-not-found]
    except ImportError:
        log.warning("llm_openai.package_not_installed", hint="pip install openai")
        return

    prompt = _build_prompt(question, docs, keywords)
    estimated_tokens = len(prompt) // 4
    log.debug(
        "llm_openai.start",
        model=model,
        n_docs=len(docs),
        estimated_tokens=estimated_tokens,
    )

    max_attempts = 3
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            client = OpenAI(api_key=api_key, timeout=_REQUEST_TIMEOUT)
            stream_obj = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
                stream=True,
            )
            for chunk in stream_obj:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    yield delta
            return  # éxito — salir del retry loop
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts and _is_retryable(exc):
                import time

                wait = 2 ** (attempt - 1)  # 1s, 2s
                log.warning(
                    "llm_openai.retry",
                    model=model,
                    attempt=attempt,
                    wait_s=wait,
                    error=str(exc),
                )
                time.sleep(wait)
            else:
                break

    log.warning(
        "llm_openai.failed",
        model=model,
        attempts=max_attempts,
        error=str(last_exc),
    )
