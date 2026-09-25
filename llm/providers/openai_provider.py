"""Proveedor OpenAI para el cliente LLM unificado.

Compatible con cualquier endpoint que hable el protocolo OpenAI Chat Completions.
Pasando ``base_url`` se reutiliza este mismo proveedor para servicios como
NVIDIA NIM (``https://integrate.api.nvidia.com/v1``), Together, Groq, etc.

Los prompts se montan en ``llm/prompts.py`` (fuente única): este módulo recibe
``(system, messages)`` ya construidos y solo gestiona la mecánica de streaming.

Hardening (B11):
    - Timeout de 30 s en la llamada a la API.
    - Retry automático (3 intentos, backoff exponencial) ante errores transitorios
      (``ConnectionError``, ``TimeoutError``, errores HTTP 408/429/500/502/503/504).
      Es la única capa: el SDK se crea con ``max_retries=0``, así que un fallo
      persistente cuesta 3 peticiones y no 9 (peor caso ≈ 93 s).
    - Log de tokens estimados pre-request y error detallado post-failure.
    - Una key rechazada (HTTP 401/403) **lanza** ``LLMAuthError`` sin reintentar,
      en vez de acabar en stream vacío como el resto de fallos. Un modelo que
      el endpoint ya no sirve (HTTP 404/410: NVIDIA responde 410 al retirar
      uno) lanza ``LLMModelUnavailableError``, por lo mismo.
    - Señal de parada (``stop``): con ella activa no se abre ningún intento
      nuevo y el backoff se corta.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, MutableMapping
from typing import Any

from llm.prompts import ChatMessage
from llm.providers import (
    AUTH_HTTP_CODES,
    MODEL_UNAVAILABLE_HTTP_CODES,
    LLMAuthError,
    LLMModelUnavailableError,
    backoff_wait,
    stop_requested,
)
from observability.logging import get_logger

log = get_logger(__name__)

# Timeout en segundos para la llamada a la API de OpenAI
_REQUEST_TIMEOUT = 30.0
# Máximo de tokens generados por respuesta
_MAX_TOKENS = 900
_TEMPERATURE = 0.2

# Errores HTTP de OpenAI que ameritan retry. El 408 lo reintentaba el SDK; con
# `max_retries=0` le toca a este bucle, y el SDK no tiene subclase para él (llega
# como `APIStatusError` genérico), así que solo se reconoce por el código.
_RETRYABLE_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})


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


def _fill_estimated_usage(
    usage_sink: MutableMapping[str, int] | None, input_tokens: int, output_chars: int
) -> None:
    """Estima el uso cuando el SDK no lo reportó (``source=1``)."""
    if usage_sink is not None and "input_tokens" not in usage_sink:
        usage_sink["input_tokens"] = input_tokens
        usage_sink["output_tokens"] = output_chars // 4
        usage_sink["source"] = 1  # estimated


def _close_stream(stream_obj: object) -> None:
    """Cierra la respuesta HTTP del stream si el objeto lo permite.

    ``getattr`` y no una llamada directa: ``create`` se tipa como
    ``ChatCompletion | Stream`` y solo el segundo tiene ``close``.
    """
    close = getattr(stream_obj, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            log.debug("llm_openai.stream_close_failed", exc_info=True)


def stream(
    system: str,
    messages: list[ChatMessage],
    model: str,
    api_key: str,
    usage_sink: MutableMapping[str, int] | None = None,
    base_url: str | None = None,
    max_tokens: int | None = None,
    chat_template_kwargs: dict[str, Any] | None = None,
    stop: threading.Event | None = None,
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
        chat_template_kwargs: Argumentos de la plantilla de chat del servidor,
            que viajan en ``extra_body``. Es una extensión de NVIDIA NIM y de
            vLLM, **no** del contrato de OpenAI: enviarla a api.openai.com
            devuelve 400, así que quien llama solo la pasa para los modelos que
            la entienden (ver ``llm/client.py``). ``None`` no añade nada al
            cuerpo, que es lo que tiene que pasar con cualquier otro proveedor.
        stop: Señal de parada del consumidor (``/ask`` la activa al vencer su
            timeout o desconectarse el cliente). Se comprueba antes de cada
            intento y corta la espera de backoff. La lectura HTTP en curso no se
            interrumpe, pero dura como mucho ``_REQUEST_TIMEOUT``. ``None``
            reintenta como siempre.

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
    # Una vez emitido el primer token, un retry re-arranca el stream desde cero y
    # el consumidor recibiría la respuesta parcial y la completa concatenadas: el
    # reintento solo es seguro ANTES del primer chunk emitido.
    yielded = False

    for attempt in range(1, max_attempts + 1):
        if stop_requested(stop):
            # Quien consume ya no espera la respuesta: otro intento solo gastaría
            # presupuesto en tokens que nadie va a leer.
            log.info("llm_openai.stopped", model=model, attempt=attempt)
            return
        try:
            # `max_retries=0`: este bucle es la única capa de retry. El SDK
            # reintenta por defecto 2 veces DENTRO de cada llamada, así que cada
            # intento de aquí llegaba a 3 peticiones de 30 s: en producción
            # (2026-09-05/06) `llm_openai.retry` salía cada ~92 s y `failed` a
            # los ~4,5 min, más del doble del `ASK_LLM_TIMEOUT_SECONDS` de `/ask`
            # (120 s), que degradaba sin que el fallback de `llm/client.py`
            # llegara a arrancar. Con una sola capa el peor caso son 3 intentos
            # de 30 s más 1 s + 2 s de backoff: ≈ 93 s.
            client = OpenAI(
                api_key=api_key,
                timeout=_REQUEST_TIMEOUT,
                base_url=base_url,
                max_retries=0,
            )
            stream_kwargs: dict[str, Any] = {
                "model": model,
                "messages": chat_messages,
                "max_tokens": max_tokens or _MAX_TOKENS,
                "temperature": _TEMPERATURE,
                "stream": True,
            }
            if usage_sink is not None:
                stream_kwargs["stream_options"] = {"include_usage": True}
            if chat_template_kwargs:
                # `extra_body` es la vía del SDK de OpenAI para mandar campos que
                # su propio esquema no conoce. Solo se añade si quien llama pasó
                # algo: un `extra_body` vacío también viaja en el JSON y algunos
                # gateways lo rechazan.
                stream_kwargs["extra_body"] = {"chat_template_kwargs": chat_template_kwargs}
            stream_obj = client.chat.completions.create(**stream_kwargs)
            output_chars = 0
            try:
                for chunk in stream_obj:
                    if chunk.choices:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            output_chars += len(delta)
                            yielded = True  # a partir de aquí el retry ya no es seguro
                            yield delta
                    elif usage_sink is not None and hasattr(chunk, "usage") and chunk.usage:
                        usage_sink["input_tokens"] = chunk.usage.prompt_tokens
                        usage_sink["output_tokens"] = chunk.usage.completion_tokens
                        usage_sink["source"] = 0  # reported by SDK
            except GeneratorExit:
                # El consumidor cerró el generador a mitad de respuesta (/ask lo
                # hace tras su timeout o una desconexión). Cerrar la respuesta
                # HTTP hace que el proveedor deje de generar. El uso se estima
                # porque el SDK solo lo reporta en el último chunk y lo generado
                # hasta aquí se factura igual: sin esto el presupuesto
                # (``llm/budget.py``) no lo vería.
                _close_stream(stream_obj)
                _fill_estimated_usage(usage_sink, estimated_tokens, output_chars)
                raise
            # Fallback si no recibimos usage del SDK
            _fill_estimated_usage(usage_sink, estimated_tokens, output_chars)
            return  # éxito — salir del retry loop
        except Exception as exc:
            last_exc = exc
            # Si ya emitimos tokens no reintentamos (duplicaría la respuesta):
            # re-lanzamos para que el consumidor perciba el corte del stream.
            if yielded:
                raise
            status_code = getattr(exc, "status_code", None)
            if status_code in AUTH_HTTP_CODES:
                # Ver `LLMAuthError`: reintentar no arregla una key rechazada, y
                # devolver vacío escondería la causa.
                log.error("llm_openai.auth_rejected", model=model, status_code=status_code)
                raise LLMAuthError(model=model, status_code=int(status_code)) from exc
            if status_code in MODEL_UNAVAILABLE_HTTP_CODES:
                # Ver `LLMModelUnavailableError`: el 410 de un modelo retirado
                # acababa en stream vacío y el consumidor no veía la causa.
                log.error("llm_openai.model_unavailable", model=model, status_code=status_code)
                raise LLMModelUnavailableError(model=model, status_code=int(status_code)) from exc
            if attempt < max_attempts and _is_retryable(exc):
                wait = 2 ** (attempt - 1)  # 1s, 2s
                log.warning(
                    "llm_openai.retry",
                    model=model,
                    attempt=attempt,
                    wait_s=wait,
                    error=str(exc),
                )
                backoff_wait(wait, stop)
            else:
                break

    log.warning(
        "llm_openai.failed",
        model=model,
        attempts=max_attempts,
        error=str(last_exc),
    )
