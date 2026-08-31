"""Cliente LLM unificado — despacha al proveedor correcto según el modelo.

Interfaz pública:
    stream_llm_response(question, docs, model, keywords, *,
                        history=None, mode="general", max_tokens=None) -> Iterator[str]
    provider_for(model) -> str  # "openai" | "anthropic" | "nvidia" | "unknown"

Los prompts y el montaje de mensajes (system + historial + contexto) viven en
``llm/prompts.py``; los providers solo reciben ``(system, messages)``.

Hardening (B11):
    - Valida ``model`` contra ``AVAILABLE_MODELS`` — lanza ``ValueError`` si desconocido.
    - Valida longitud de ``question`` (3-2000 chars), cantidad de docs (<=50)
      y el historial de conversación (<=20 mensajes de <=4000 chars).
    - ``_get_key`` loguea warning si el secreto no puede leerse, en vez de silenciar.
    - Prometheus histogram ``llm_request_duration_seconds`` para latencia end-to-end.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

from llm.prompts import ChatMessage, PromptMode, build_messages
from observability.logging import get_logger

log = get_logger(__name__)

# ── Configuración de modelos ───────────────────────────────────────────────────

# Prefijos para despacho de proveedor
_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-")
_ANTHROPIC_PREFIXES = ("claude-",)

# NVIDIA NIM expone una API compatible con OpenAI. Los modelos llegan con formato
# "namespace/modelo" (p. ej. "deepseek-ai/deepseek-v4-flash-0731"), y el "/" en
# el nombre actúa como discriminador frente a los modelos OpenAI/Anthropic.
# El endpoint es configurable vía NVIDIA_BASE_URL para apuntar a un gateway propio.
_NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")

# Modelos mostrados en el selectbox del dashboard y aceptados por el endpoint /ask.
#
# Los modelos NVIDIA NIM se validaron contra el catálogo vivo
# (GET https://integrate.api.nvidia.com/v1/models, público, sin auth) el
# 2026-08-13. NVIDIA retira modelos sin aviso: `deepseek-ai/deepseek-v4-pro` —
# el default anterior — llegó a su end-of-life el 2026-08-07T09:00Z y desde
# entonces devuelve 410, lo que dejó la IA caída seis días en silencio. Antes de
# tocar esta lista, verificá contra ese endpoint que el id sigue existiendo.
#
# Los cuatro modelos NIM marcados abajo como "razonamiento" generan una traza de
# reasoning ANTES de la respuesta final, y esa traza consume el presupuesto de
# `max_tokens` del provider (900 en /ask, 1500 en /resumen). Si la traza se lo
# come entero, el stream llega vacío y /ask degrada — mismo síntoma que un
# proveedor caído. Se controla con `chat_template_kwargs`, que este cliente
# todavía NO envía (ver docs/IMPROVEMENT_BACKLOG.md).
AVAILABLE_MODELS: list[str] = [
    # ── NVIDIA NIM (free tier: sin coste, limitado por RPM/créditos de la key) ─
    # 284B totales / 13B activos. Tier "flash": el de menor coste computacional
    # por token de la lista y por eso el de mejor relación velocidad/calidad.
    "deepseek-ai/deepseek-v4-flash-0731",
    # 744B / 40B activos. Razonamiento, pero con modo non-thinking explícito.
    "z-ai/glm-5.2",
    # 120B / 12B activos, 1M contexto, español soportado. Razonamiento.
    "nvidia/nemotron-3-super-120b-a12b",
    # 550B / 55B activos, 1M contexto. Razonamiento. El más lento del lote.
    "nvidia/nemotron-3-ultra-550b-a55b",
    # 428B / 23B activos, 1M contexto. Razonamiento; afinado a coding/agentes.
    "minimaxai/minimax-m3",
    # ── Proveedores de pago (requieren OPENAI_API_KEY / ANTHROPIC_API_KEY) ────
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-3.5-turbo",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
]

# Modelo por defecto cuando el cliente no especifica uno.
# Criterio: mejor relación velocidad/calidad. Con 13B de parámetros activos es
# el más rápido por token de la lista, y los foros de NVIDIA lo reportan por
# encima del V4 Pro (1.6T) que sustituye. Además es de la misma familia contra
# la que están afinados los prompts de `llm/prompts.py`.
DEFAULT_MODEL = "deepseek-ai/deepseek-v4-flash-0731"

# Límites de entrada
#
# ``MAX_QUESTION_LEN`` es público a propósito: no solo acota lo que teclea un
# usuario en /ask, también acota las plantillas de prompt que este repo pasa
# como ``question`` (la ficha de pliego, el etiquetado de tecnología). Cuando
# una de esas constantes creció por encima del tope, la funcionalidad entera
# dejó de funcionar con un ValueError antes de llegar al proveedor —y sin un
# nombre público no había forma de que un test lo fijara. Ver
# ``tests/test_tender_fact_sheet.py::test_extraction_question_fits_llm_limit``.
MAX_QUESTION_LEN = 2000
_MIN_QUESTION_LEN = 3
_MAX_DOCS = 50
_MAX_HISTORY_MESSAGES = 20
_MAX_HISTORY_CONTENT_LEN = 4000

# ── Precio por millón de tokens (USD): (input, output) ────────────────────────
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # NVIDIA NIM — en el free tier de build.nvidia.com estas llamadas no se
    # facturan (el límite son los créditos y el RPM de la key). Aun así llevan
    # precio NOCIONAL de referencia, por dos motivos: `_record_usage` solo
    # alimenta el BudgetGuard si el modelo está en este dict, así que un 0.0
    # dejaría el breaker de coste sin contar nada; y si algún día se pasa a un
    # plan de pago el control ya está puesto. Son estimaciones por clase de
    # modelo, no tarifas publicadas: ajustar al plan real que se contrate.
    "deepseek-ai/deepseek-v4-flash-0731": (0.10, 0.40),
    "z-ai/glm-5.2": (0.60, 2.00),
    "nvidia/nemotron-3-super-120b-a12b": (0.20, 0.80),
    "nvidia/nemotron-3-ultra-550b-a55b": (0.90, 3.60),
    "minimaxai/minimax-m3": (0.30, 1.20),
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


def _validate_request(
    question: str,
    docs: list[dict[str, Any]],
    model: str,
    history: list[ChatMessage] | None = None,
) -> None:
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
    if len(question) > MAX_QUESTION_LEN:
        raise ValueError(
            f"La pregunta excede el máximo de {MAX_QUESTION_LEN} caracteres "
            f"(recibido: {len(question)})."
        )
    if len(docs) > _MAX_DOCS:
        raise ValueError(f"Se proporcionaron {len(docs)} documentos; el máximo es {_MAX_DOCS}.")
    if history:
        # Defensa en profundidad: la API ya limita esto vía Pydantic.
        if len(history) > _MAX_HISTORY_MESSAGES:
            raise ValueError(
                f"El historial tiene {len(history)} mensajes; el máximo es {_MAX_HISTORY_MESSAGES}."
            )
        for msg in history:
            if msg.get("role") not in ("user", "assistant"):
                raise ValueError(f"Rol de historial inválido: {msg.get('role')!r}.")
            if len(msg.get("content", "")) > _MAX_HISTORY_CONTENT_LEN:
                raise ValueError(
                    f"Un mensaje del historial excede {_MAX_HISTORY_CONTENT_LEN} caracteres."
                )


# ── API pública ────────────────────────────────────────────────────────────────


def stream_llm_response(
    question: str,
    docs: list[dict[str, Any]],
    model: str,
    keywords: list[str],
    *,
    history: list[ChatMessage] | None = None,
    mode: PromptMode = "general",
    max_tokens: int | None = None,
) -> Iterator[str]:
    """Genera tokens LLM en streaming delegando al proveedor correcto.

    Args:
        question: Pregunta del usuario (3-2000 caracteres).
        docs: Lista de dicts con claves ``id_externo``, ``titulo``,
              ``organo_contratacion``, ``importe``, ``estado``, ``descripcion``
              y opcionalmente ``chunks`` (fragmentos de pliego). Máximo 50.
        model: Nombre del modelo. Debe estar en ``AVAILABLE_MODELS``.
        keywords: Palabras clave para el extracto contextual.
        history: Historial previo de la conversación (no incluye ``question``).
            Máximo 20 mensajes de 4000 chars; se sanea y trunca en
            ``llm/prompts.py``. No se persiste.
        mode: Modo de prompt — ``general`` (corpus + conocimiento general),
            ``licitacion`` (un expediente con sus pliegos) o ``resumen``.
        max_tokens: Límite de tokens de salida; ``None`` usa el default del
            provider.

    Yields:
        Fragmentos de texto del modelo a medida que llegan.

    Raises:
        ValueError: Si ``model`` no está en ``AVAILABLE_MODELS``, o si
                    ``question``/``docs``/``history`` están fuera de rango.
        LLMBudgetExceeded: Si el presupuesto está agotado y
                    ``LLM_BUDGET_MODE=enforce`` (RFC llm-dependencia-gestionada).
    """
    _validate_request(question, docs, model, history)

    # Breaker de coste ANTES de llamar al proveedor: en enforce corta el gasto,
    # en monitor solo instrumenta. Nota: al ser esto un generador, el check corre
    # en la primera iteración; /ask hace además un check eager pre-stream para
    # poder responder 429 antes de abrir el SSE.
    from llm.budget import get_budget_guard

    get_budget_guard().check()

    p = provider_for(model)
    system, messages = build_messages(question, docs, keywords, mode=mode, history=history)
    t0 = time.monotonic()
    status = "ok"
    usage: dict[str, int] = {}

    try:
        if p == "openai":
            from llm.providers.openai_provider import stream as _stream_openai

            yield from _stream_openai(
                system,
                messages,
                model,
                _get_key("OPENAI_API_KEY"),
                usage_sink=usage,
                max_tokens=max_tokens,
            )
        elif p == "anthropic":
            from llm.providers.anthropic_provider import stream as _stream_anthropic

            yield from _stream_anthropic(
                system,
                messages,
                model,
                _get_key("ANTHROPIC_API_KEY"),
                usage_sink=usage,
                max_tokens=max_tokens,
            )
        elif p == "nvidia":
            # NVIDIA NIM reutiliza el proveedor OpenAI con su base_url propio.
            from llm.providers.openai_provider import stream as _stream_nvidia

            yield from _stream_nvidia(
                system,
                messages,
                model,
                _get_key("NVIDIA_API_KEY"),
                usage_sink=usage,
                base_url=_NVIDIA_BASE_URL,
                max_tokens=max_tokens,
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
