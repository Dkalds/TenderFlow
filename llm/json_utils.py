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


def _cerrar_json_cortado(texto: str) -> str | None:
    """``texto`` hasta su último elemento completo, con los cierres que faltan.

    Se corta justo tras el último ``}``/``]`` que cierra un elemento anidado
    —un objeto de una lista, una lista de una clave— y se añaden los cierres de
    lo que quedaba abierto en ese punto. ``None`` si no hay ningún elemento
    completo o si el objeto raíz llegó a cerrarse (no era un corte).
    """
    pendientes: list[str] = []
    en_cadena = escapado = False
    corte: tuple[int, str] | None = None
    for posicion, letra in enumerate(texto):
        if en_cadena:
            if escapado:
                escapado = False
            elif letra == "\\":
                escapado = True
            elif letra == '"':
                en_cadena = False
        elif letra == '"':
            en_cadena = True
        elif letra in "{[":
            pendientes.append("}" if letra == "{" else "]")
        elif letra in "}]":
            if len(pendientes) <= 1:
                return None
            pendientes.pop()
            corte = (posicion + 1, "".join(reversed(pendientes)))
    if corte is None:
        return None
    fin, cierres = corte
    return texto[:fin] + cierres


def extract_json_object_admitiendo_corte(raw: str) -> tuple[dict[str, object], bool]:
    """Como :func:`extract_json_object`, pero recupera un objeto cortado por ``max_tokens``.

    Devuelve ``(objeto, cortado)``. Una salida que llega al tope de tokens acaba
    a media cadena; ``extract_json_object`` la recorta hasta el último ``}`` y
    falla con «Expecting ',' delimiter». Así fallaron las fichas de dos pliegos
    largos (2026-10-24 y 2026-10-30, ~28 600 caracteres: los 8000 tokens de
    salida), tres intentos cada una para llegar al mismo corte. Aquí se
    conserva todo lo que estaba completo y se descarta el último elemento a
    medias.

    Solo para quien valida cada elemento por separado y puede marcar el
    resultado como incompleto (la ficha del pliego). Una lista que debe estar
    entera —las puntuaciones de todos los licitadores de un acta— no debe
    usarla: un corte la dejaría corta sin que nada lo dijera.
    """
    try:
        return extract_json_object(raw), False
    except json.JSONDecodeError:
        cleaned = _FENCE_CLOSE_RE.sub("", _FENCE_OPEN_RE.sub("", raw.strip()))
        cerrado = _cerrar_json_cortado(cleaned[cleaned.find("{") :])
        if cerrado is None:
            raise
        try:
            value = json.loads(cerrado)
        except json.JSONDecodeError:
            raise ValueError(
                "El extractor devolvió un JSON cortado que no se pudo recuperar"
            ) from None
        if not isinstance(value, dict):
            raise ValueError("La respuesta del LLM no es un objeto JSON") from None
        return value, True
