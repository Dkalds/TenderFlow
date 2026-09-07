"""Filtros para detectar licitaciones relacionadas con tecnologías enterprise.

Desde C5.6 (D28) el diccionario **no** se congela al importar el módulo: viene
de ``services/tech_dictionary.py``, que lo lee de ``tecnologias_keywords`` y cae
a ``config/keywords.py`` como semilla. Editar una keyword en ``/ops`` deja de
necesitar un despliegue.

Los patrones compilados se cachean por **huella del diccionario**: compilar seis
regex por aviso sería absurdo, y compararlos por huella hace que un cambio se
aplique solo, sin nadie que tenga que acordarse de invalidar nada.
"""

from __future__ import annotations

import re

from observability.logging import get_logger

log = get_logger(__name__)

#: ``huella -> {tecnologia: patrón}``. Una entrada por diccionario distinto, y
#: en la práctica una sola: el diccionario cambia cada muchos días.
_PATRONES_POR_HUELLA: dict[str, dict[str, re.Pattern[str]]] = {}


def _compilar(keywords: list[str]) -> re.Pattern[str]:
    """Regex con ``\b`` a los lados: 'sap' no debe casar dentro de 'desaparecer'."""
    return re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
        flags=re.IGNORECASE,
    )


def _patrones() -> dict[str, re.Pattern[str]]:
    """Patrones del diccionario vigente, compilados una vez por versión."""
    from services.tech_dictionary import huella, vigente

    diccionario = vigente()
    clave = huella(diccionario)
    patrones = _PATRONES_POR_HUELLA.get(clave)
    if patrones is None:
        patrones = {tech: _compilar(keywords) for tech, keywords in diccionario.items() if keywords}
        # Sin poda: el diccionario cambia cada muchos días y cada entrada son
        # unos pocos regex. Un LRU aquí sería complejidad sin problema detrás.
        _PATRONES_POR_HUELLA[clave] = patrones
    return patrones


def matches_sap(*texts: str | None) -> tuple[bool, list[str]]:
    """Comprueba si alguno de los textos contiene keywords SAP.

    Returns:
        (coincide, lista_de_keywords_encontradas)
    """
    patron = _patrones().get("SAP")
    if patron is None:
        return False, []
    found: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in patron.findall(text):
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
    for tech, pattern in _patrones().items():
        found: set[str] = set()
        for text in texts:
            if not text:
                continue
            for match in pattern.findall(text):
                found.add(match.lower())
        if found:
            result[tech] = sorted(found)
    return bool(result), result
