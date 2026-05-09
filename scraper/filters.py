"""Filtros para detectar licitaciones relacionadas con SAP."""

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


def matches_sap_ml(*texts: str | None, threshold: float = 0.70) -> tuple[bool, float]:
    """Segunda pasada: usa el clasificador ML para detectar licitaciones SAP
    que no contienen keywords explícitas pero el modelo las clasifica como SAP.

    Solo se invoca cuando ``matches_sap`` devuelve False (complemento, no reemplazo).

    Args:
        texts: Textos a evaluar (título, descripción, etc.).
        threshold: Confianza mínima para considerar positivo.

    Returns:
        (es_sap_ml, confianza) — confianza en [0, 1]. Si el modelo no está
        disponible, devuelve (False, 0.0) sin propagar excepciones.
    """
    from scraper.ml_classifier import SAPClassifier

    if not SAPClassifier.is_available():
        return False, 0.0

    combined = " ".join(t for t in texts if t).strip()
    if not combined:
        return False, 0.0

    try:
        clf = SAPClassifier.load()
        return clf.predict(combined)
    except Exception as e:
        log.warning("ml_filter.error", error=str(e))
        return False, 0.0
