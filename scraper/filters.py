"""Filtros para detectar licitaciones relacionadas con tecnologías enterprise."""

from __future__ import annotations

import re
import unicodedata

from config import SAP_KEYWORDS
from config.keywords import keywords_presentes, patron_de_keywords
from observability.logging import get_logger

log = get_logger(__name__)

# Límites de palabra para evitar falsos positivos ('sap' dentro de
# 'desaparecer'). Se compila por `config.keywords.patron_de_keywords` —el mismo
# camino que `services.tecnologias_diccionario.patrones`— y no con un
# `\b(...)\b` propio: hoy ninguna keyword de esta lista empieza o acaba en
# símbolo, pero el día que entre una (`.net`, `c#`) el `\b` la dejaría muerta
# sin que nada lo dijera, que es lo que pasó en el diccionario de tecnologías.
_SAP_PATTERN = patron_de_keywords(SAP_KEYWORDS)


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


def _normalizados(texts: tuple[str | None, ...]) -> list[str]:
    """Los textos no vacíos, en NFC.

    El patrón compila cada letra con sus variantes precompuestas («ó»), y el
    texto extraído de un PDF llega a menudo en NFD («o» + tilde aparte): sin
    esto la comprobación previa de cada label no casaría.
    """
    return [unicodedata.normalize("NFC", t) for t in texts if t]


def _keywords_por_tecnologia() -> dict[str, list[str]]:
    """Las keywords del diccionario vigente, para devolverlas en su forma canónica."""
    from services.tecnologias_diccionario import vigente

    return vigente()[0]


def matches_sap(*texts: str | None) -> tuple[bool, list[str]]:
    """Comprueba si alguno de los textos contiene keywords SAP.

    Returns:
        (coincide, lista_de_keywords_encontradas), en la forma del diccionario.
    """
    textos = _normalizados(texts)
    if not any(_SAP_PATTERN.search(t) for t in textos):
        return False, []
    found = keywords_presentes(textos, SAP_KEYWORDS)
    return bool(found), found


def matches_technology(
    *texts: str | None,
) -> tuple[bool, dict[str, list[str]]]:
    """Comprueba si alguno de los textos contiene keywords de cualquier tecnología.

    El patrón de cada tecnología decide **si** casa (una pasada por label); las
    keywords que se devuelven son todas las que aparecen, en la forma del
    diccionario (:func:`config.keywords.keywords_presentes`), y no el trozo de
    texto casado: «FIREWALLS» devuelve `firewall`, y «SAP FI/CO» devuelve
    `sap` y `sap fi/co`.

    Returns:
        (coincide, {tecnología: [keywords_encontradas]})
    """
    textos = _normalizados(texts)
    if not textos:
        return False, {}
    keywords = _keywords_por_tecnologia()
    result: dict[str, list[str]] = {}
    for tech, pattern in _tech_patterns().items():
        if not any(pattern.search(t) for t in textos):
            continue
        found = keywords_presentes(textos, keywords.get(tech, ()))
        if found:
            result[tech] = found
    return bool(result), result
