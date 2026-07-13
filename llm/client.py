"""Cliente LLM unificado — despacha al proveedor correcto según el modelo.

Interfaz pública:
    stream_llm_response(question, docs, model, keywords) -> Iterator[str]
    provider_for(model) -> str  # "openai" | "anthropic" | "unknown"

Hardening (B11):
    - Valida ``model`` contra ``AVAILABLE_MODELS`` — lanza ``ValueError`` si desconocido.
    - Valida longitud de ``question`` (3-2000 chars) y cantidad de docs (<=50).
    - ``_get_key`` loguea warning si el secreto no puede leerse, en vez de silenciar.
    - Prometheus histogram ``llm_request_duration_seconds`` para latencia end-to-end.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# ── Configuración de modelos ───────────────────────────────────────────────────

# Prefijos para despacho de proveedor
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-")
_ANTHROPIC_PREFIXES = ("claude-",)

# NVIDIA NIM expone una API compatible con OpenAI. Los modelos llegan con formato
# "namespace/modelo" (p. ej. "deepseek-ai/deepseek-v4-pro"), por lo que el "/" en
# el nombre actúa como discriminador frente a los modelos OpenAI/Anthropic.
# El endpoint es configurable vía NVIDIA_BASE_URL para apuntar a un gateway propio.
_NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Modelos mostrados en el selectbox del dashboard y aceptados por el endpoint /ask
AVAILABLE_MODELS: list[str] = [
    "deepseek-ai/deepseek-v4-pro",
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-3.5-turbo",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]

# Modelo por defecto cuando el cliente no especifica uno.
DEFAULT_MODEL = "deepseek-ai/deepseek-v4-pro"

# Límites de entrada
_MAX_QUESTION_LEN = 2000
_MIN_QUESTION_LEN = 3
_MAX_DOCS = 50

# ── Precio por millón de tokens (USD): (input, output) ────────────────────────
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # NVIDIA NIM — precio aproximado, ajustar según el plan contratado.
    "deepseek-ai/deepseek-v4-pro": (0.27, 1.10),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-3.5-turbo": (0.50, 1.50),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (0.80, 4.00),
}


# ── Prometheus histogram (opcional — no falla si prometheus no está instalado) ─


def _get_llm_histogram() -> Any:
    """Devuelve el histogram Prometheus para latencia LLM, o un stub si no disponible."""
    try:
        from prometheus_client import Histogram

        return Histogram(
            "llm_request_duration_seconds",
            "Latencia end-to-end de peticiones LLM (desde llamada hasta primer token)",
            ["model", "provider", "status"],
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0],
        )
    except Exception:
        return None


# Inicialización lazy del histogram para evitar errores en imports tempranos
_llm_histogram: Any = None
_llm_histogram_init = False

_llm_tokens_counter: Any = None
_llm_cost_counter: Any = None
_llm_counters_init = False


def _histogram() -> Any:
    global _llm_histogram, _llm_histogram_init
    if not _llm_histogram_init:
        _llm_histogram_init = True
        try:
            _llm_histogram = _get_llm_histogram()
        except Exception:
            log.debug("llm_histogram_init_failed", exc_info=True)
    return _llm_histogram


def _get_token_counters() -> tuple[Any, Any]:
    """Devuelve (tokens_counter, cost_counter) o (None, None)."""
    global _llm_tokens_counter, _llm_cost_counter, _llm_counters_init
    if not _llm_counters_init:
        _llm_counters_init = True
        try:
            from prometheus_client import Counter

            _llm_tokens_counter = Counter(
                "llm_tokens_total",
                "Tokens consumidos por el cliente LLM",
                ["model", "provider", "direction", "source"],
            )
            _llm_cost_counter = Counter(
                "llm_cost_usd_total",
                "Coste estimado en USD por llamadas LLM",
                ["model", "provider"],
            )
        except Exception:
            log.debug("llm_counters_init_failed", exc_info=True)
    return _llm_tokens_counter, _llm_cost_counter


def _record_usage(model: str, provider: str, usage: dict[str, int]) -> None:
    """Registra tokens y coste en Prometheus si hay datos."""
    if not usage:
        return
    tokens_c, cost_c = _get_token_counters()
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    source_label = "reported" if usage.get("source", 1) == 0 else "estimated"

    if tokens_c is not None:
        try:
            tokens_c.labels(
                model=model, provider=provider, direction="input", source=source_label
            ).inc(input_tokens)
            tokens_c.labels(
                model=model, provider=provider, direction="output", source=source_label
            ).inc(output_tokens)
        except Exception:
            pass

    if model in _PRICE_PER_MTOK:
        price_in, price_out = _PRICE_PER_MTOK[model]
        cost = (input_tokens * price_in + output_tokens * price_out) / 1_000_000
        if cost_c is not None:
            try:
                cost_c.labels(model=model, provider=provider).inc(cost)
            except Exception:
                pass
        # Alimenta el presupuesto (RFC llm-dependencia-gestionada) con el mismo
        # cálculo que nutre llm_cost_usd_total. Best-effort: nunca rompe el stream.
        try:
            from llm.budget import get_budget_guard

            get_budget_guard().record(cost)
        except Exception:
            log.debug("llm_budget_record_failed", exc_info=True)
    else:
        log.debug("llm_cost_unknown_model", model=model)


# ── Helpers ────────────────────────────────────────────────────────────────────


def provider_for(model: str) -> str:
    """Devuelve el nombre del proveedor para un modelo dado."""
    if any(model.startswith(p) for p in _OPENAI_PREFIXES):
        return "openai"
    if any(model.startswith(p) for p in _ANTHROPIC_PREFIXES):
        return "anthropic"
    # Los modelos de NVIDIA NIM usan la convención "namespace/modelo".
    if "/" in model:
        return "nvidia"
    return "unknown"


def _get_key(env_var: str) -> str:
    """Lee una clave de config.secrets con fallback a os.environ.

    Loguea warning si la lectura desde secrets falla (en vez de silenciarla),
    para facilitar diagnóstico de problemas de configuración.
    """
    try:
        from config.secrets import get_secret

        key = get_secret(env_var)
        if key:
            return key
    except Exception as exc:
        log.warning("llm_client.secret_read_failed", env_var=env_var, error=str(exc))
    val = os.environ.get(env_var, "")
    if not val:
        log.debug("llm_client.api_key_empty", env_var=env_var)
    return val


def _validate_request(question: str, docs: list[dict[str, Any]], model: str) -> None:
    """Valida los parámetros de entrada antes de llamar al proveedor.

    Raises:
        ValueError: Si alguno de los parámetros es inválido.
    """
    if model not in AVAILABLE_MODELS:
        raise ValueError(
            f"Modelo '{model}' no disponible. Modelos soportados: {', '.join(AVAILABLE_MODELS)}"
        )
    if not question or len(question) < _MIN_QUESTION_LEN:
        raise ValueError(f"La pregunta debe tener al menos {_MIN_QUESTION_LEN} caracteres.")
    if len(question) > _MAX_QUESTION_LEN:
        raise ValueError(
            f"La pregunta excede el máximo de {_MAX_QUESTION_LEN} caracteres "
            f"(recibido: {len(question)})."
        )
    if len(docs) > _MAX_DOCS:
        raise ValueError(f"Se proporcionaron {len(docs)} documentos; el máximo es {_MAX_DOCS}.")


# ── API pública ────────────────────────────────────────────────────────────────


def stream_llm_response(
    question: str,
    docs: list[dict[str, Any]],
    model: str,
    keywords: list[str],
) -> Iterator[str]:
    """Genera tokens LLM en streaming delegando al proveedor correcto.

    Args:
        question: Pregunta del usuario (3-2000 caracteres).
        docs: Lista de dicts con claves ``id_externo``, ``titulo``,
              ``organo_contratacion``, ``importe``, ``estado``, ``descripcion``.
              Máximo 50 documentos.
        model: Nombre del modelo. Debe estar en ``AVAILABLE_MODELS``.
        keywords: Palabras clave para el extracto contextual.

    Yields:
        Fragmentos de texto del modelo a medida que llegan.

    Raises:
        ValueError: Si ``model`` no está en ``AVAILABLE_MODELS``, o si
                    ``question`` está fuera de rango, o si hay demasiados docs.
        LLMBudgetExceeded: Si el presupuesto está agotado y
                    ``LLM_BUDGET_MODE=enforce`` (RFC llm-dependencia-gestionada).
    """
    _validate_request(question, docs, model)

    # Breaker de coste ANTES de llamar al proveedor: en enforce corta el gasto,
    # en monitor solo instrumenta. Nota: al ser esto un generador, el check corre
    # en la primera iteración; /ask hace además un check eager pre-stream para
    # poder responder 429 antes de abrir el SSE.
    from llm.budget import get_budget_guard

    get_budget_guard().check()

    p = provider_for(model)
    t0 = time.monotonic()
    status = "ok"
    usage: dict[str, int] = {}

    try:
        if p == "openai":
            from llm.providers.openai_provider import stream as _stream_openai

            yield from _stream_openai(
                question, docs, model, keywords, _get_key("OPENAI_API_KEY"), usage_sink=usage
            )
        elif p == "anthropic":
            from llm.providers.anthropic_provider import stream as _stream_anthropic

            yield from _stream_anthropic(
                question, docs, model, keywords, _get_key("ANTHROPIC_API_KEY"), usage_sink=usage
            )
        elif p == "nvidia":
            # NVIDIA NIM reutiliza el proveedor OpenAI con su base_url propio.
            from llm.providers.openai_provider import stream as _stream_nvidia

            yield from _stream_nvidia(
                question,
                docs,
                model,
                keywords,
                _get_key("NVIDIA_API_KEY"),
                usage_sink=usage,
                base_url=_NVIDIA_BASE_URL,
            )
        else:
            raise ValueError(f"Proveedor desconocido para modelo '{model}'")
    except Exception:
        status = "error"
        raise
    finally:
        elapsed = time.monotonic() - t0
        hist = _histogram()
        if hist is not None:
            try:
                hist.labels(model=model, provider=p, status=status).observe(elapsed)
            except Exception:
                log.debug("llm_histogram_observe_failed", exc_info=True)
        _record_usage(model, p, usage)
        log.debug(
            "llm_client.stream_done",
            model=model,
            provider=p,
            elapsed_ms=int(elapsed * 1000),
            status=status,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
