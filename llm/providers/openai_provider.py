"""Proveedor OpenAI para el cliente LLM unificado.

Compatible con cualquier endpoint que hable el protocolo OpenAI Chat Completions.
Pasando ``base_url`` se reutiliza este mismo proveedor para servicios como
NVIDIA NIM (``https://integrate.api.nvidia.com/v1``), Together, Groq, etc.

Los prompts se montan en ``llm/prompts.py`` (fuente única): este módulo recibe
``(system, messages)`` ya construidos y solo gestiona la mecánica de streaming.

Hardening (B11):
    - Timeout de 30 s en la llamada a la API.
    - Retry automático (3 intentos, backoff exponencial) ante errores transitorios
      (``ConnectionError``, ``TimeoutError``, errores HTTP 429/500/502/503).
    - Log de tokens estimados pre-request y error detallado post-failure.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from typing import Any

from llm.prompts import ChatMessage
from observability.logging import get_logger

log = get_logger(__name__)

# Timeout en segundos para la llamada a la API de OpenAI
_REQUEST_TIMEOUT = 30.0
# Máximo de tokens generados por respuesta
_MAX_TOKENS = 900
_TEMPERATURE = 0.2

# Errores HTTP de OpenAI que ameritan retry
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


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
    system: str,
    messages: list[ChatMessage],
    model: str,
    api_key: str,
    usage_sink: MutableMapping[str, int] | None = None,
    base_url: str | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Streaming OpenAI (o endpoint compatible) con retry y timeout.

    Args:
        system: System prompt ya montado (ver ``llm/prompts.py``); se antepone
            como mensaje ``{"role": "system"}``.
        messages: Conversación en formato canónico (roles user/assistant).
        model: Nombre del modelo OpenAI.
        api_key: Clave de API del proveedor.
        usage_sink: Si se provee, se rellena con input_tokens, output_tokens, source.
        base_url: URL base de la API. ``None`` usa el endpoint oficial de OpenAI;
            con un valor (p. ej. NVIDIA NIM) se enruta al endpoint compatible.
        max_tokens: Límite de tokens de salida; ``None`` usa el default del módulo.

    Yields:
        Fragmentos de texto del modelo.
    """
    if not api_key:
        log.warning("llm_openai.api_key_missing", model=model)
        return

    try:
        from openai import OpenAI
    except ImportError:
        log.warning("llm_openai.package_not_installed", hint="pip install openai")
        return

    chat_messages = [{"role": "system", "content": system}, *messages]
    estimated_tokens = (len(system) + sum(len(m["content"]) for m in messages)) // 4
    log.debug(
        "llm_openai.start",
        model=model,
        n_messages=len(messages),
        estimated_tokens=estimated_tokens,
    )

    max_attempts = 3
    last_exc: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            client = OpenAI(api_key=api_key, timeout=_REQUEST_TIMEOUT, base_url=base_url)
            stream_kwargs: dict[str, Any] = {
                "model": model,
                "messages": chat_messages,
                "max_tokens": max_tokens or _MAX_TOKENS,
                "temperature": _TEMPERATURE,
                "stream": True,
            }
            if usage_sink is not None:
                stream_kwargs["stream_options"] = {"include_usage": True}
            stream_obj = client.chat.completions.create(**stream_kwargs)
            output_chars = 0
            for chunk in stream_obj:
                if chunk.choices:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        output_chars += len(delta)
                        yield delta
                elif usage_sink is not None and hasattr(chunk, "usage") and chunk.usage:
                    usage_sink["input_tokens"] = chunk.usage.prompt_tokens
                    usage_sink["output_tokens"] = chunk.usage.completion_tokens
                    usage_sink["source"] = 0  # reported by SDK
            # Fallback si no recibimos usage del SDK
            if usage_sink is not None and "input_tokens" not in usage_sink:
                usage_sink["input_tokens"] = estimated_tokens
                usage_sink["output_tokens"] = output_chars // 4
                usage_sink["source"] = 1  # estimated
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
