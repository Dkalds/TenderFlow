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


class RespuestaVacia(ValueError):
    """El proveedor no emitió un solo token.

    Es un fallo **distinto** de «respondió sin JSON» y se arregla de otra
    manera: un stream vacío apunta al modelo o al presupuesto de tokens —los
    modelos de razonamiento se comen el ``max_tokens`` en la traza y devuelven
    nada—, mientras que una respuesta en prosa apunta al prompt.

    Compartían mensaje, y por eso 203 fichas fallidas en producción decían «el
    extractor no devolvió un objeto JSON» sin que nadie pudiera saber cuál de
    las dos cosas había pasado.
    """


def extract_json_object(raw: str) -> dict[str, Any]:
    """Acepta JSON puro o un único bloque fenced y rechaza texto sin objeto.

    Raises:
        RespuestaVacia: si el proveedor no emitió nada.
        ValueError: si emitió algo pero no contiene un objeto JSON.
    """
    if not raw or not raw.strip():
        raise RespuestaVacia(
            "El proveedor devolvió un stream vacío: ni un token. Suele ser el "
            "presupuesto de max_tokens agotado por la traza de un modelo de "
            "razonamiento, o el modelo retirado del catálogo."
        )
    cleaned = _FENCE_OPEN_RE.sub("", raw.strip())
    cleaned = _FENCE_CLOSE_RE.sub("", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(
            "El extractor respondió sin ningún objeto JSON "
            f"({len(cleaned)} caracteres, empieza por: {cleaned[:60]!r})"
        )
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("La respuesta del LLM no es un objeto JSON")
    return value
