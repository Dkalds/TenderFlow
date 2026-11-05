"""El segmento CPV-4 de un código CPV, en un solo sitio.

Había siete copias en ``services/``. ``db.sql_fragments.cpv4`` es otra cosa a
propósito: gemela de ``cpv4_sql``, no hace ``strip`` y devuelve cadena vacía,
porque decide la clave de duplicados que se publica.
"""

from __future__ import annotations


def cpv4(cpv: object) -> str | None:
    """Los cuatro primeros dígitos de un CPV, o ``None`` si no los tiene.

    Acepta lo que traiga una fila o un DataFrame: un ``NaN`` de pandas se lee
    como ``"nan"`` y sale ``None`` como cualquier otro valor ilegible.
    """
    if cpv is None:
        return None
    texto = str(cpv).strip()[:4]
    return texto if len(texto) == 4 and texto.isascii() and texto.isdigit() else None
