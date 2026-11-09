"""Metadatos de accesibilidad comunes a los PDFs que genera el producto.

``reportlab`` solo escribe título, autor e idioma si se los pasan, y ninguno de
los tres maquetadores lo hacía salvo el título de la ficha: el PDF tabular y el
guion salían sin ningún metadato. Un documento sin ``/Lang`` ni título no lo
anuncia bien un lector de pantalla, y quien exporta una ficha a una
administración sujeta al RD 1112/2018 entrega un PDF que no cumple.

Lo que esto **no** hace es etiquetar el contenido: ``reportlab`` no genera la
estructura (orden de lectura, encabezados, texto alternativo) que exige PDF/UA.
Ese resto necesita otro renderer y sigue en el backlog.
"""

from __future__ import annotations

#: Idioma del contenido. Es el idioma base del documento; un pliego en catalán
#: o gallego sigue siendo un documento en español con citas.
IDIOMA = "es-ES"

#: Autor de los documentos. El producto los emite, no el usuario que los pide.
AUTOR = "TenderFlow"


def metadatos(*, titulo: str, asunto: str | None = None) -> dict[str, str | int]:
    """Los argumentos de metadatos que acepta ``SimpleDocTemplate``.

    ``displayDocTitle`` hace que el visor muestre el título del documento y no
    el nombre del fichero: reportlab sí lo soporta y PDF/UA lo exige. El resto
    —estructura y orden de lectura— no.
    """
    return {
        "title": titulo,
        "author": AUTOR,
        "creator": AUTOR,
        "producer": AUTOR,
        "subject": (asunto or "").strip() or titulo,
        "lang": IDIOMA,
        "displayDocTitle": 1,
    }


__all__ = ["AUTOR", "IDIOMA", "metadatos"]
