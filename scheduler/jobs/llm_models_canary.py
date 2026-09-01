"""Canary del catálogo de modelos NVIDIA NIM.

NVIDIA retira modelos sin aviso: ``deepseek-ai/deepseek-v4-pro`` (el default
anterior de ``llm/client.py``) llegó a su EOL el 2026-08-07 y devolvió 410
durante seis días antes de que nadie lo notara — la IA entera degradada en
silencio. La cadena de fallback de ``stream_llm_response`` mitiga el impacto;
este canary avisa ANTES: compara los modelos NIM de ``AVAILABLE_MODELS``
contra el catálogo vivo (endpoint público, sin auth) y loguea a nivel error
si alguno desapareció, que es la señal para actualizar la lista.

Job ligero (una petición HTTP): no toca BD ni proveedor de pago.
"""

from __future__ import annotations

import os
from typing import Any

from observability.logging import get_logger

log = get_logger(__name__)

# Mismo default (y misma variable de entorno) que ``llm/client.py``.
_CATALOG_TIMEOUT_SECONDS = 20


def _catalog_url() -> str:
    base = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    return f"{base.rstrip('/')}/models"


def run() -> dict[str, Any]:
    """Devuelve ``{"checked": n, "missing": [...], "error": str | None}``.

    Un fallo de red no es un hallazgo: se reporta como ``error`` y no marca
    modelos como ausentes (fail-open, igual que el resto del scraper).
    """
    import requests

    from llm.client import AVAILABLE_MODELS, provider_for

    nim_models = [m for m in AVAILABLE_MODELS if provider_for(m) == "nvidia"]
    result: dict[str, Any] = {"checked": len(nim_models), "missing": [], "error": None}
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
    result["missing"] = missing
    if missing:
        # Nivel error a propósito: es la alerta accionable de "actualizá
        # AVAILABLE_MODELS antes de que el 410 lo haga por vos".
        log.error("llm_models_canary_models_missing", models=missing)
    else:
        log.info("llm_models_canary_ok", checked=len(nim_models))
    return result
