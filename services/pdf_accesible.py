"""Los PDFs que genera el producto: Typst, PDF/UA-1 y datos fuera del marcado.

Ficha, informes tabulares y guion se maquetaban con ``reportlab``, que no
etiqueta el contenido: el PDF salía con título e idioma pero sin estructura
(orden de lectura, encabezados, cabeceras de tabla), y quien lo entrega a una
administración sujeta al RD 1112/2018 entregaba un PDF que no cumple. Desde el
2026-11-24 los tres salen de plantillas Typst (``services/plantillas_pdf/``)
compiladas con el estándar PDF/UA-1: árbol de estructura, ``/Lang``, título
mostrado por el visor y fuentes embebidas. Si una plantilla rompe el estándar,
Typst no genera el PDF: falla la compilación, no la accesibilidad.

Los datos entran como JSON en ``sys.inputs`` y las plantillas los pintan como
valores, nunca como marcado: un título de licitación (texto de la fuente) o el
nombre de una organización (texto libre del cliente) con ``#``, ``*`` o
``<img src=...>`` sale literal. Con ``reportlab`` había que escapar a mano cada
cadena que pasaba por ``Paragraph``; aquí no hay nada que escapar.

Las fuentes son las que la rueda de Typst lleva dentro
(``ignore_system_fonts``): el PDF sale igual en CI, en la imagen de la API y
en un portátil, sin depender de lo que tenga instalado cada máquina.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

#: Idioma del contenido (``/Lang``). Lo fija la plantilla común; se exporta para
#: los tests. Un pliego en catalán o gallego sigue siendo un documento en
#: español con citas.
IDIOMA = "es-ES"

#: Autor de los documentos. El producto los emite, no el usuario que los pide.
AUTOR = "TenderFlow"

_PLANTILLAS = Path(__file__).resolve().parent / "plantillas_pdf"


def compilar(plantilla: str, datos: Mapping[str, object]) -> bytes:
    """El PDF/UA-1 de ``plantillas_pdf/<plantilla>.typ`` con ``datos``.

    El import va dentro: el módulo de Typst carga un binario de ~30 MB y este
    fichero lo importa cualquier proceso que toque ``services/``.
    """
    import typst

    pdf = typst.compile(
        str(_PLANTILLAS / f"{plantilla}.typ"),
        sys_inputs={"datos": json.dumps(datos, ensure_ascii=False)},
        pdf_standards="ua-1",
        ignore_system_fonts=True,
    )
    return bytes(pdf)


def sello(formato: str) -> str:
    """La línea «generado el…» en UTC, con el formato de ``strftime`` dado."""
    return datetime.now(UTC).strftime(formato)


__all__ = ["AUTOR", "IDIOMA", "compilar", "sello"]
