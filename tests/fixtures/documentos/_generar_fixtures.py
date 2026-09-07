#!/usr/bin/env python3
"""Genera los ficheros de ``tests/fixtures/documentos/`` (S8.2 y S8.3).

Los fixtures se commitean —son binarios pequeños y deterministas— pero se
generan desde aquí para que se sepa **qué contienen y por qué**, y para poder
rehacerlos si alguna dependencia cambia de formato. No forma parte de la suite:
se ejecuta a mano.

    python tests/fixtures/documentos/_generar_fixtures.py

Qué produce y para qué sirve cada uno:

- ``pliego_con_texto.pdf`` — PDF con capa de texto. Verifica la extracción
  normal y, sobre todo, que un PDF así **no pasa por OCR**.
- ``pliego_escaneado.pdf`` — la misma frase, pero rasterizada como imagen y sin
  capa de texto: es el caso que antes de S8.3 terminaba en ``error``.
- ``pliego.docx`` / ``pliego.odt`` — un pliego corto en cada formato ofimático,
  con párrafos suficientes para ejercitar la convención de página lógica.
- ``adjuntos.zip`` — un PDF y un DOCX dentro de un ZIP, que es como PLACSP
  publica los expedientes con varios anexos.
- ``zip_bomb.zip`` — tres entradas ``.pdf`` de 2 MB de ceros (comprimen a unos
  pocos KB). Con ``MAX_DOCUMENT_SIZE_BYTES`` bajado en el test, prueba que el
  tope de tamaño descomprimido corta antes de materializar nada.
- ``zip_muchas_entradas.zip`` — 60 entradas, por encima de ``_ZIP_MAX_ENTRADAS``.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from pathlib import Path

DESTINO = Path(__file__).parent

#: El texto que se busca luego en las aserciones. Lleva acentos a propósito: la
#: extracción tiene que sobrevivir al viaje por PDF, DOCX, ODT y OCR.
FRASE = "Objeto del contrato: mantenimiento de la plataforma SAP"

PARRAFOS = [
    "PLIEGO DE CLAUSULAS ADMINISTRATIVAS PARTICULARES",
    FRASE,
    "Clausula segunda: el plazo de ejecucion sera de veinticuatro meses.",
    "Clausula tercera: la solvencia tecnica se acreditara con tres contratos.",
    *[f"Clausula adicional numero {n}: condicion de detalle." for n in range(4, 60)],
]


def _pdf_con_texto() -> bytes:
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 750, FRASE)
    c.showPage()
    c.drawString(72, 750, "Segunda pagina del pliego con texto.")
    c.save()
    return buf.getvalue()


def _pdf_escaneado() -> bytes:
    """PDF de una sola imagen: sin capa de texto, como un pliego escaneado."""
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    imagen = Image.new("RGB", (1200, 200), "white")
    dibujo = ImageDraw.Draw(imagen)
    # Fuente por defecto de Pillow: pequeña, pero tesseract la reconoce y, lo
    # importante para el test, pypdf no ve NINGUN texto en el PDF resultante.
    dibujo.text((20, 80), FRASE, fill="black")
    escalada = imagen.resize((2400, 400))

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawImage(ImageReader(escalada), 40, 500, width=520, height=90)
    c.save()
    return buf.getvalue()


_DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


def _docx() -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    cuerpo = "".join(f'<w:p><w:r><w:t xml:space="preserve">{p}</w:t></w:r></w:p>' for p in PARRAFOS)
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{ns}"><w:body>{cuerpo}</w:body></w:document>'
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _DOCX_CONTENT_TYPES)
        z.writestr("_rels/.rels", _DOCX_RELS)
        z.writestr("word/document.xml", documento)
    return buf.getvalue()


_ODT_MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">
<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>"""


def _odt() -> bytes:
    office = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    text_ns = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    cuerpo = "".join(f"<text:p>{p}</text:p>" for p in PARRAFOS)
    contenido = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content xmlns:office="{office}" xmlns:text="{text_ns}" '
        'office:version="1.2">'
        f"<office:body><office:text>{cuerpo}</office:text></office:body>"
        "</office:document-content>"
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # El `mimetype` va primero y SIN comprimir: lo exige el estándar ODF y
        # es como los lectores reconocen el formato antes de descomprimir nada.
        z.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/vnd.oasis.opendocument.text",
            compress_type=zipfile.ZIP_STORED,
        )
        z.writestr("META-INF/manifest.xml", _ODT_MANIFEST)
        z.writestr("content.xml", contenido)
    return buf.getvalue()


def _adjuntos_zip(pdf: bytes, docx: bytes) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("01_pcap.pdf", pdf)
        z.writestr("02_ppt.docx", docx)
        # Ruido que el extractor tiene que ignorar sin quejarse.
        z.writestr("03_notas.txt", "no procesable dentro del zip")
        z.writestr("04_anexo.zip", b"PK\x03\x04 anidado, se ignora a proposito")
    return buf.getvalue()


def _zip_bomb() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in range(3):
            z.writestr(f"{n}_bomba.pdf", b"\0" * (2 * 1024 * 1024))
    return buf.getvalue()


def _zip_muchas_entradas() -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for n in range(60):
            z.writestr(f"anexo_{n:03d}.pdf", b"relleno")
    return buf.getvalue()


def main() -> None:
    pdf = _pdf_con_texto()
    docx = _docx()
    ficheros = {
        "pliego_con_texto.pdf": pdf,
        "pliego_escaneado.pdf": _pdf_escaneado(),
        "pliego.docx": docx,
        "pliego.odt": _odt(),
        "adjuntos.zip": _adjuntos_zip(pdf, docx),
        "zip_bomb.zip": _zip_bomb(),
        "zip_muchas_entradas.zip": _zip_muchas_entradas(),
    }
    for nombre, datos in ficheros.items():
        (DESTINO / nombre).write_bytes(datos)
        print(f"{nombre}: {len(datos):,} bytes")


if __name__ == "__main__":
    main()
