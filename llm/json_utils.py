"""Parseo defensivo de la salida JSON de un LLM.

Ningún provider del repo expone ``response_format``/JSON mode (ver
``llm/providers/openai_provider.py``), así que el "JSON estricto" es solo una
instrucción del prompt: el modelo puede envolver la respuesta en un bloque
fenced o acompañarla de texto. Este helper acepta esas variantes y rechaza lo
que no contenga un objeto.

Vive en ``llm/`` y no en un consumidor concreto porque lo comparten la
extracción de fichas de pliego (``services/rag/fact_sheet.py``) y el etiquetado
batch de tecnología (``services/llm_tech_labeling.py``).
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"\s*```\s*$")


def extract_json_object(raw: str) -> dict[str, Any]:
    """Acepta JSON puro o un único bloque fenced y rechaza texto sin objeto."""
    cleaned = _FENCE_OPEN_RE.sub("", raw.strip())
    cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("El extractor no devolvió un objeto JSON")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("La respuesta del LLM no es un objeto JSON")
    return value
