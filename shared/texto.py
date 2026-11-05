"""Plegado de texto para comparar sin tildes.

Había nueve copias de «NFKD y quitar los diacríticos», y una (la de las
menciones) usaba NFD, que no pliega los caracteres de compatibilidad («º»,
«ﬁ»). Esta es la única; ``config.keywords.plegar`` queda como gemela porque
``config`` está por debajo de ``shared`` y no puede importarla (AGENTS.md §2).
"""

from __future__ import annotations

import unicodedata


def sin_tildes(texto: str) -> str:
    """Quita los diacríticos sin tocar mayúsculas: «Administración» → «Administracion»."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))
