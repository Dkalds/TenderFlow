"""Canary del catálogo de modelos NVIDIA NIM.

NVIDIA retira modelos sin aviso: ``deepseek-ai/deepseek-v4-pro`` (el default
anterior de ``llm/client.py``) llegó a su EOL el 2026-08-07 y devolvió 410
durante seis días antes de que nadie lo notara — la IA entera degradada en
silencio. La cadena de fallback de ``stream_llm_response`` mitiga el impacto;
este canary avisa ANTES con dos comprobaciones por modelo NIM de
``AVAILABLE_MODELS``:

1. **Catálogo** (``GET /v1/models``, público, sin auth): el modelo sigue
   listado. Es lo que dio la alerta del EOL de deepseek.
2. **Servicio** (una petición de chat mínima, con ``NVIDIA_API_KEY``): el
   modelo contesta. Estar en el catálogo no prueba que se sirva: el
   2026-10-20 ``nvidia/nemotron-3-super-120b-a12b`` seguía listado y el chat
   devolvía 404, y el canary dio ``llm_models_canary_ok``.

La petición de chat pasa por ``llm.client.stream_llm_response`` (sin fallback,
``max_tokens`` mínimo, modo non-thinking por el registro del cliente), así que
respeta el ``BudgetGuard`` y su coste se registra como el de cualquier llamada
LLM. Solo un 404/410 cuenta como modelo no servido; un stream vacío (timeout o
5xx tras los reintentos del provider) es inconcluso y se reporta aparte, sin
tumbar el paso. Sin key o con el presupuesto agotado en ``enforce`` se queda
en el catálogo y lo dice en el log.

Job ligero: una petición al catálogo y una de pocos tokens por modelo NIM; no
toca BD.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from observability.logging import get_logger

log = get_logger(__name__)

# Mismo default (y misma variable de entorno) que ``llm/client.py``.
_CATALOG_TIMEOUT_SECONDS = 20


def _catalog_url() -> str:
    base = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    return f"{base.rstrip('/')}/models"


# Petición de servicio: ``max_tokens`` mínimo y una pregunta que no invita a
# razonar. El modo non-thinking de los NIM de razonamiento lo pone el cliente
# (``REASONING_TEMPLATE_KWARGS``), no este módulo.
_PROBE_QUESTION = "Responde solo: ok"
_PROBE_MAX_TOKENS = 8

_Probe = Literal["ok", "unserved", "inconclusive", "auth", "budget"]


def _probe_chat(model: str) -> _Probe:
    """Una petición de chat mínima a ``model``, por el cliente LLM del repo.

    ``fallback=False``: si el modelo falla hay que saberlo, no que otro
    conteste por él. El ``check()`` del ``BudgetGuard`` corre dentro de
    ``stream_llm_response`` y el coste se registra en ``_record_usage``.
    """
    from llm.budget import LLMBudgetExceeded
    from llm.client import stream_llm_response
    from llm.providers import LLMAuthError, LLMModelUnavailableError

    try:
        emitted = any(
            True
            for _ in stream_llm_response(
                _PROBE_QUESTION,
                [],
                model,
                [],
                max_tokens=_PROBE_MAX_TOKENS,
                fallback=False,
            )
        )
    except LLMModelUnavailableError as exc:
        log.error(
            "llm_models_canary_chat_unserved",
            model=model,
            status_code=exc.status_code,
        )
        return "unserved"
    except LLMAuthError as exc:
        log.error("llm_models_canary_chat_auth_rejected", model=model, status_code=exc.status_code)
        return "auth"
    except LLMBudgetExceeded as exc:
        log.warning("llm_models_canary_chat_budget_exceeded", model=model, error=str(exc))
        return "budget"
    except Exception as exc:
        log.warning("llm_models_canary_chat_failed", model=model, error=str(exc))
        return "inconclusive"
    if not emitted:
        # El provider se traga timeouts y 5xx tras sus reintentos y devuelve un
        # stream vacío: no distingue «caído un rato» de «no responde». No es un
        # hallazgo del catálogo, pero tampoco un verde.
        log.warning("llm_models_canary_chat_empty", model=model)
        return "inconclusive"
    return "ok"


def run() -> dict[str, Any]:
    """Devuelve el resultado del canary como un dict.

    Claves:

    - ``checked``: modelos NIM de ``AVAILABLE_MODELS``.
    - ``missing``: modelos que ya no se pueden usar, ausentes del catálogo o
      listados pero con el chat en 404/410 (``unserved`` es el segundo grupo).
    - ``unserved``: listados en el catálogo cuyo chat responde 404/410.
    - ``unverified``: la petición de chat no concluyó (stream vacío o error
      inesperado); no cuentan como ausentes.
    - ``chat_checked``: modelos a los que sí se les hizo la petición de chat.
    - ``chat_skipped``: ``None`` si se hicieron las peticiones de chat, o el
      motivo por el que no (``no_key``, ``auth_rejected``, ``budget``).
    - ``error``: fallo de red al leer el catálogo.

    Un fallo de red no es un hallazgo: se reporta como ``error`` y no marca
    modelos como ausentes (fail-open, igual que el resto del scraper).
    """
    import requests

    from llm.client import AVAILABLE_MODELS, provider_for, provider_key_available

    nim_models = [m for m in AVAILABLE_MODELS if provider_for(m) == "nvidia"]
    result: dict[str, Any] = {
        "checked": len(nim_models),
        "missing": [],
        "unserved": [],
        "unverified": [],
        "chat_checked": 0,
        "chat_skipped": None,
        "error": None,
    }
    if not nim_models:
        return result

    try:
        resp = requests.get(_catalog_url(), timeout=_CATALOG_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
        catalog = {str(item.get("id")) for item in payload.get("data", [])}
    except Exception as exc:
        log.warning("llm_models_canary_fetch_failed", error=str(exc))
        result["error"] = str(exc)
        return result

    missing = [m for m in nim_models if m not in catalog]
    listed = [m for m in nim_models if m in catalog]

    if listed and not provider_key_available("nvidia"):
        result["chat_skipped"] = "no_key"
        log.info("llm_models_canary_chat_skipped", reason="no_key", models=len(listed))
    elif listed:
        for model in listed:
            outcome = _probe_chat(model)
            if outcome in ("auth", "budget"):
                # La key (o el presupuesto) es la misma para todos los modelos:
                # insistir solo repetiría el rechazo o gastaría de más.
                result["chat_skipped"] = "auth_rejected" if outcome == "auth" else "budget"
                break
            result["chat_checked"] += 1
            if outcome == "unserved":
                result["unserved"].append(model)
            elif outcome == "inconclusive":
                result["unverified"].append(model)

    missing += result["unserved"]
    result["missing"] = missing
    if missing:
        # Nivel error a propósito: es la alerta accionable de "actualizá
        # AVAILABLE_MODELS antes de que el 410 lo haga por vos".
        log.error(
            "llm_models_canary_models_missing",
            models=missing,
            unserved=result["unserved"],
        )
    else:
        log.info(
            "llm_models_canary_ok",
            checked=len(nim_models),
            chat_checked=result["chat_checked"],
            chat_skipped=result["chat_skipped"],
            unverified=result["unverified"],
        )
    return result
