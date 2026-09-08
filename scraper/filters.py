"""Filtros para detectar licitaciones relacionadas con tecnologías enterprise."""

from __future__ import annotations

import re

from config import SAP_KEYWORDS
from observability.logging import get_logger

log = get_logger(__name__)

# Compilamos un regex con word boundaries para evitar falsos positivos
# (ej: 'sap' dentro de otra palabra como 'desaparecer')
_SAP_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in SAP_KEYWORDS) + r")\b",
    flags=re.IGNORECASE,
)


def _tech_patterns() -> dict[str, re.Pattern[str]]:
    """Patrones por tecnología del diccionario **vigente** (C5.6).

    Era un `dict` de nivel de módulo compilado al importar. Con el diccionario
    en base de datos eso lo congelaba en el arranque del proceso: una keyword
    añadida desde `/ops` no habría entrado hasta el siguiente despliegue, que es
    exactamente lo que el ítem viene a quitar.

    No es caro: `services.tecnologias_diccionario.patrones()` memoiza por
    versión del diccionario, así que la compilación ocurre una vez por cambio y
    no una vez por texto.
    """
    from services.tecnologias_diccionario import patrones

    return patrones()


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
    for tech, pattern in _tech_patterns().items():
        found: set[str] = set()
        for text in texts:
            if not text:
                continue
            for match in pattern.findall(text):
                found.add(match.lower())
        if found:
            result[tech] = sorted(found)
    return bool(result), result
