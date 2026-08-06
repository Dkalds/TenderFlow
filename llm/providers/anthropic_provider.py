"""Proveedor Anthropic (Claude) para el cliente LLM unificado.

Usa la API de Messages con streaming. Soporta modelos claude-* incluyendo
Claude Sonnet 4.5 (``claude-sonnet-4-5``) y Claude Haiku 4.5
(``claude-haiku-4-5``).

Requiere ``pip install anthropic`` y la variable ``ANTHROPIC_API_KEY``.

Los prompts se montan en ``llm/prompts.py`` (fuente única): este módulo recibe
``(system, messages)`` ya construidos y solo gestiona la mecánica de streaming.

Hardening (B11):
    - Timeout de 30 s en la llamada a la API.
    - Retry automático (3 intentos, backoff exponencial) ante errores transitorios.
    - Log de API key missing como warning en vez de silencio.
"""

from __future__ import annotations

from collections.abc import Iterator, MutableMapping

from llm.prompts import ChatMessage
from observability.logging import get_logger

log = get_logger(__name__)

_MAX_TOKENS = 1024
_TEMPERATURE = 0.2
_REQUEST_TIMEOUT = 30.0

_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


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
    system: str,
    messages: list[ChatMessage],
    model: str,
    api_key: str,
    usage_sink: MutableMapping[str, int] | None = None,
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Streaming Anthropic Messages API con retry y timeout.

    Args:
        system: System prompt ya montado (ver ``llm/prompts.py``).
        messages: Conversación en formato canónico (roles user/assistant
            alternados, primero user — garantizado por ``build_messages``).
        model: Nombre del modelo Anthropic.
        api_key: Clave de API de Anthropic.
        usage_sink: Si se provee, se rellena con input_tokens, output_tokens, source.
        max_tokens: Límite de tokens de salida; ``None`` usa el default del módulo.

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

    prompt_chars = len(system) + sum(len(m["content"]) for m in messages)
    log.debug(
        "llm_anthropic.start",
        model=model,
        n_messages=len(messages),
        estimated_tokens=prompt_chars // 4,
    )

    max_attempts = 3
    last_exc: Exception | None = None
    # Una vez emitido el primer token, un retry re-arranca el stream desde cero y
    # el consumidor recibiría la respuesta parcial y la completa concatenadas: el
    # reintento solo es seguro ANTES del primer chunk emitido.
    yielded = False

    for attempt in range(1, max_attempts + 1):
        try:
            client = anthropic.Anthropic(
                api_key=api_key,
                timeout=_REQUEST_TIMEOUT,
            )
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens or _MAX_TOKENS,
                system=system,
                messages=list(messages),
            ) as stream_obj:
                for text in stream_obj.text_stream:
                    if text:
                        yielded = True  # a partir de aquí el retry ya no es seguro
                        yield text
                # Capturar usage real del SDK
                if usage_sink is not None:
                    try:
                        final_msg = stream_obj.get_final_message()
                        usage_sink["input_tokens"] = final_msg.usage.input_tokens
                        usage_sink["output_tokens"] = final_msg.usage.output_tokens
                        usage_sink["source"] = 0  # reported by SDK
                    except Exception:
                        # Fallback: estimar
                        usage_sink["input_tokens"] = prompt_chars // 4
                        usage_sink["output_tokens"] = 0
                        usage_sink["source"] = 1  # estimated
            return  # éxito
        except Exception as exc:
            last_exc = exc
            # Si ya emitimos tokens no reintentamos (duplicaría la respuesta):
            # re-lanzamos para que el consumidor perciba el corte del stream.
            if yielded:
                raise
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
