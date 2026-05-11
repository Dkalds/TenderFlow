"""Filtros para detectar licitaciones relacionadas con tecnologías enterprise."""

from __future__ import annotations

import re

from config import SAP_KEYWORDS, TECHNOLOGY_KEYWORDS
from observability.logging import get_logger

log = get_logger(__name__)

# Compilamos un regex con word boundaries para evitar falsos positivos
# (ej: 'sap' dentro de otra palabra como 'desaparecer')
_SAP_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in SAP_KEYWORDS) + r")\b",
    flags=re.IGNORECASE,
)

# Patrones compilados por tecnología
_TECH_PATTERNS: dict[str, re.Pattern[str]] = {
    tech: re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
        flags=re.IGNORECASE,
    )
    for tech, keywords in TECHNOLOGY_KEYWORDS.items()
}


def matches_sap(*texts: str | None) -> tuple[bool, list[str]]:
    """Comprueba si alguno de los textos contiene keywords SAP.

    Returns:
        (coincide, lista_de_keywords_encontradas)
    """
    found: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in _SAP_PATTERN.findall(text):
            found.add(match.lower())
    return bool(found), sorted(found)


def matches_technology(
    *texts: str | None,
) -> tuple[bool, dict[str, list[str]]]:
    """Comprueba si alguno de los textos contiene keywords de cualquier tecnología.

    Returns:
        (coincide, {tecnología: [keywords_encontradas]})
    """
    result: dict[str, list[str]] = {}
    for tech, pattern in _TECH_PATTERNS.items():
        found: set[str] = set()
        for text in texts:
            if not text:
                continue
            for match in pattern.findall(text):
                found.add(match.lower())
        if found:
            result[tech] = sorted(found)
    return bool(result), result
