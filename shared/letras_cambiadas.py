"""Reparar los PDF cuyo texto sale con las tildes cambiadas («ClÆusula», «tambiØn»).

Algunos pliegos usan una fuente con codificación propia que pypdf decodifica
con la tabla equivocada. Medido en producción el 2026-11-03 sobre una muestra
del 6 % de ``documento_pages``: el 1,5 % de las páginas, con una sustitución
fija y uno a uno —``á→Æ``, ``é→Ø``, ``ú→œ``, ``ñ→æ`` y ``Í→˝``— mientras la
``í`` y la ``ó`` salen bien. Ese texto rompe todo lo que lo lee: el selector de
páginas de la ficha (una página con «ContendrÆ» no puntúa por «contendrá»), la
búsqueda por texto y los embeddings.

Se repara el documento entero solo si tiene la huella —una de esas letras entre
dos minúsculas— al menos :data:`MIN_HUELLAS` veces: en un pliego en castellano
eso no ocurre de forma legítima, y el umbral deja fuera un nombre extranjero
suelto. La sustitución es carácter a carácter, así que los offsets de cada
página no cambian y las citas guardadas siguen apuntando al mismo sitio.

Pura y sin dependencias: la usan la extracción (``scraper/document_fetcher.py``)
y la reparación de lo ya guardado (``scripts/reparar_letras_cambiadas.py``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

_LETRAS: Final = str.maketrans({"Æ": "á", "Ø": "é", "œ": "ú", "æ": "ñ", "˝": "Í"})
_HUELLA: Final = re.compile(r"[a-z][ÆØœ][a-z]")

#: Huellas mínimas en el documento para repararlo; los afectados tienen decenas.
MIN_HUELLAS: Final = 3

#: La misma huella en la sintaxis de Postgres, para preseleccionar en SQL.
HUELLA_SQL: Final = "[a-z][ÆØœ][a-z]"


def tiene_letras_cambiadas(paginas: Iterable[str]) -> bool:
    """¿Tiene el documento la huella de la tabla equivocada?"""
    huellas = 0
    for texto in paginas:
        huellas += len(_HUELLA.findall(texto))
        if huellas >= MIN_HUELLAS:
            return True
    return False


def reparar_paginas(paginas: list[str]) -> list[str]:
    """Las páginas reparadas si el documento tiene la huella; si no, las mismas."""
    if not tiene_letras_cambiadas(paginas):
        return paginas
    return [reparar_texto(texto) for texto in paginas]


def reparar_texto(texto: str) -> str:
    """La sustitución sin comprobar la huella: para un texto ya diagnosticado."""
    return texto.translate(_LETRAS)
