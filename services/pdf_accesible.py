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
import re
import unicodedata
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

#: Lo que sustituye a un carácter que la fuente embebida no puede pintar.
SUSTITUTO = "?"

#: Bloques que Libertinus no cubre y que sí llegan (nombres de empresa, avisos
#: de TED): CJK, hangul y los ideogramas de compatibilidad. Se quitan antes de
#: compilar para no reintentar carácter a carácter.
_SIN_GLIFO = re.compile("[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff]")

#: El mensaje de Typst cuando un carácter no está en la fuente.
_NO_SE_PINTA = re.compile(r'the text `"(.+?)"` could not be displayed')

#: Reintentos con el carácter que Typst nombra antes de rendirse.
_MAX_REINTENTOS = 50


def _limpio(texto: str) -> str:
    """El texto sin lo que haría fallar la compilación PDF/UA-1.

    PDF/UA prohíbe el glifo ``.notdef`` y Typst, en vez de pintar un cuadro,
    no genera el PDF. Los de control (salvo salto de línea y tabulador) se
    quitan; el área privada (la viñeta U+F0B7 que Word deja en los pliegos),
    los astrales (emoji) y los bloques de :data:`_SIN_GLIFO` se sustituyen.
    """
    salida: list[str] = []
    for c in texto:
        categoria = unicodedata.category(c)
        if categoria in ("Cc", "Cf") and c not in "\n\t":
            continue
        if categoria in ("Co", "Cs", "Cn") or ord(c) > 0xFFFF:
            salida.append(SUSTITUTO)
            continue
        salida.append(c)
    return _SIN_GLIFO.sub(SUSTITUTO, "".join(salida))


def _sustituir(valor: object, viejo: str | None = None) -> object:
    """``valor`` con cada cadena limpia, o con ``viejo`` cambiado por el sustituto."""
    if isinstance(valor, str):
        return _limpio(valor) if viejo is None else valor.replace(viejo, SUSTITUTO)
    if isinstance(valor, Mapping):
        return {k: _sustituir(v, viejo) for k, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [_sustituir(v, viejo) for v in valor]
    return valor


def _simbolo_sin_glifo(error: Exception) -> str | None:
    """El carácter que Typst no pudo pintar, si el error es ese."""
    hallado = _NO_SE_PINTA.search(str(error))
    if hallado is None:
        return None
    # Typst lo escribe como literal suyo: `\u{f0b7}` para lo no imprimible.
    return re.sub(r"\\u\{([0-9a-fA-F]+)\}", lambda m: chr(int(m.group(1), 16)), hallado.group(1))


def compilar(plantilla: str, datos: Mapping[str, object]) -> bytes:
    """El PDF/UA-1 de ``plantillas_pdf/<plantilla>.typ`` con ``datos``.

    Un carácter sin glifo en la fuente cambia por :data:`SUSTITUTO` en vez de
    tumbar el documento: con ``reportlab`` salía un cuadro y el PDF se
    generaba, y un emoji en el nombre de una organización no puede dejar sin
    adjunto el informe semanal.

    El import va dentro: el módulo de Typst carga un binario de ~30 MB y este
    fichero lo importa cualquier proceso que toque ``services/``.
    """
    import typst

    entrada = _sustituir(datos)
    for _ in range(_MAX_REINTENTOS):
        try:
            pdf = typst.compile(
                str(_PLANTILLAS / f"{plantilla}.typ"),
                sys_inputs={"datos": json.dumps(entrada, ensure_ascii=False)},
                pdf_standards="ua-1",
                ignore_system_fonts=True,
            )
        except Exception as error:
            simbolo = _simbolo_sin_glifo(error)
            if not simbolo:
                raise
            entrada = _sustituir(entrada, simbolo)
            continue
        return bytes(pdf)
    raise RuntimeError(f"{plantilla}: más de {_MAX_REINTENTOS} caracteres sin glifo")


def sello(formato: str) -> str:
    """La línea «generado el…» en UTC, con el formato de ``strftime`` dado."""
    return datetime.now(UTC).strftime(formato)


__all__ = ["AUTOR", "IDIOMA", "compilar", "sello"]
