"""Filtros para detectar licitaciones relacionadas con tecnologías enterprise."""

from __future__ import annotations

import unicodedata

from config import SAP_KEYWORDS
from config.keywords import keywords_presentes, patron_de_keywords
from observability.logging import get_logger

# Reexportado: lo usan los conectores; vive en `services/` porque solo lee el
# diccionario de tecnologías y `services/tech_signal.py` lo necesita también.
from services.tecnologias_diccionario import matches_technology as matches_technology

log = get_logger(__name__)

# Límites de palabra para evitar falsos positivos ('sap' dentro de
# 'desaparecer'). Se compila por `config.keywords.patron_de_keywords` —el mismo
# camino que `services.tecnologias_diccionario.patrones`— y no con un
# `\b(...)\b` propio: hoy ninguna keyword de esta lista empieza o acaba en
# símbolo, pero el día que entre una (`.net`, `c#`) el `\b` la dejaría muerta
# sin que nada lo dijera, que es lo que pasó en el diccionario de tecnologías.
_SAP_PATTERN = patron_de_keywords(SAP_KEYWORDS)


def _normalizados(texts: tuple[str | None, ...]) -> list[str]:
    """Los textos no vacíos, en NFC.

    El patrón compila cada letra con sus variantes precompuestas («ó»), y el
    texto extraído de un PDF llega a menudo en NFD («o» + tilde aparte): sin
    esto la comprobación previa de cada label no casaría.
    """
    return [unicodedata.normalize("NFC", t) for t in texts if t]


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
