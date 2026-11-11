"""DOCX con la biblioteca estándar (2026-11): ``word/document.xml`` sin ``python-docx``.

Como en ``test_unit_document_fetcher_odf_zip.py``, los binarios se construyen en
el propio test para que cada caso diga qué trae el fichero.

Lo que fija:

- Se lee sin ``python-docx`` (la imagen de la API no lo trae: arrastra ``lxml``).
- Párrafos y filas de tabla en orden documental, con tabuladores y saltos.
- No entra lo que no es contenido: texto borrado o movido del control de
  cambios, códigos de campo, la copia VML de un cuadro de texto y las paradas
  de tabulación de las propiedades del párrafo.
- Un ``DOCTYPE`` se rechaza antes de expandir entidades, y un DOCX sin parte
  principal o roto es ``error``, no ``unsupported``.
"""

from __future__ import annotations

import io
import sys
import zipfile

import pytest

from scraper.document_fetcher import (
    CONTENT_TYPE_DOCX,
    DocumentFetchError,
    UnsupportedDocumentError,
    _extract_paginas,
)

_NS = (
    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
)


def _zip(entradas: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archivo:
        for nombre, datos in entradas.items():
            archivo.writestr(nombre, datos)
    return buffer.getvalue()


def _docx(cuerpo: str, *, prologo: str = "") -> bytes:
    xml = f'<?xml version="1.0"?>{prologo}<w:document {_NS}><w:body>{cuerpo}</w:body></w:document>'
    return _zip({"[Content_Types].xml": b"<Types/>", "word/document.xml": xml.encode()})


def _p(*runs: str) -> str:
    return "<w:p>" + "".join(f"<w:r>{r}</w:r>" for r in runs) + "</w:p>"


def _texto(contenido: bytes) -> str:
    return "\n".join(p.texto for p in _extract_paginas(contenido, CONTENT_TYPE_DOCX))


def test_se_lee_sin_python_docx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "docx", None)  # `import docx` lanza ImportError
    assert _texto(_docx(_p("<w:t>Cláusula primera</w:t>"))) == "Cláusula primera"


def test_parrafos_y_tablas_en_orden_documental() -> None:
    tabla = (
        "<w:tbl><w:tr>"
        f"<w:tc>{_p('<w:t>Lote 1</w:t>')}</w:tc>"
        f"<w:tc>{_p('<w:t>120.000</w:t>')}</w:tc>"
        f"<w:tc>{_p('<w:t></w:t>')}</w:tc>"
        "</w:tr></w:tbl>"
    )
    cuerpo = _p("<w:t>Antes</w:t>") + tabla + _p("<w:t>Después</w:t>")
    assert _texto(_docx(cuerpo)) == "Antes\nLote 1 | 120.000\nDespués"


def test_un_parrafo_partido_en_runs_se_une_con_tabuladores_y_saltos() -> None:
    parrafo = _p(
        '<w:t xml:space="preserve">Plazo: </w:t>',
        "<w:tab/><w:t>30 días</w:t>",
        "<w:br/><w:t>prorrogable</w:t>",
        "<w:t>no</w:t><w:noBreakHyphen/><w:t>sujeto</w:t>",
    )
    assert _texto(_docx(parrafo)) == "Plazo: \t30 días\nprorrogableno-sujeto"


def test_no_entra_lo_que_no_es_contenido() -> None:
    parrafo = (
        "<w:p>"
        '<w:pPr><w:tabs><w:tab w:val="left" w:pos="720"/></w:tabs></w:pPr>'
        "<w:r><w:t>Importe 100.000</w:t></w:r>"
        "<w:del><w:r><w:delText>Importe 90.000</w:delText></w:r></w:del>"
        "<w:moveFrom><w:r><w:t>texto movido</w:t></w:r></w:moveFrom>"
        '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        "<w:r><mc:AlternateContent>"
        "<mc:Choice><w:txbxContent>" + _p("<w:t>Cuadro</w:t>") + "</w:txbxContent></mc:Choice>"
        "<mc:Fallback><w:txbxContent>" + _p("<w:t>Cuadro</w:t>") + "</w:txbxContent></mc:Fallback>"
        "</mc:AlternateContent></w:r>"
        "</w:p>"
    )
    # El cuadro de texto es un párrafo anidado: sale una vez, al cerrarse.
    assert _texto(_docx(parrafo)) == "Cuadro\nImporte 100.000"


def test_un_doctype_se_rechaza_antes_de_expandir_entidades() -> None:
    bomba = '<!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    with pytest.raises(DocumentFetchError, match="DOCTYPE") as exc:
        _texto(_docx(_p("<w:t>&b;</w:t>"), prologo=bomba))
    assert not isinstance(exc.value, UnsupportedDocumentError)


def test_sin_parte_principal_roto_o_vacio_es_error() -> None:
    with pytest.raises(DocumentFetchError, match=r"word/document\.xml"):
        _texto(_zip({"[Content_Types].xml": b"<Types/>"}))
    with pytest.raises(DocumentFetchError, match="DOCX corrupto"):
        _texto(_docx("<w:p><w:r><w:t>sin cerrar</w:r></w:p>"))
    with pytest.raises(DocumentFetchError, match="sin texto"):
        _texto(_docx(_p("<w:t>  </w:t>")))


def test_el_marcador_de_un_campo_sin_rellenar_no_es_contenido() -> None:
    vacio = (
        '<w:p><w:r><w:t xml:space="preserve">Procedimiento: </w:t></w:r>'
        "<w:sdt><w:sdtPr><w:showingPlcHdr/></w:sdtPr>"
        "<w:sdtContent><w:r><w:t>Elija un elemento.</w:t></w:r></w:sdtContent></w:sdt></w:p>"
    )
    relleno = (
        '<w:p><w:r><w:t xml:space="preserve">Lugar: </w:t></w:r>'
        "<w:sdt><w:sdtPr/><w:sdtContent><w:r><w:t>Madrid</w:t></w:r></w:sdtContent></w:sdt></w:p>"
    )
    assert _texto(_docx(vacio + relleno)) == "Procedimiento:\nLugar: Madrid"


def test_el_indice_automatico_no_duplica_los_encabezados() -> None:
    indice = (
        "<w:sdt><w:sdtPr><w:docPartObj>"
        '<w:docPartGallery w:val="Table of Contents"/></w:docPartObj></w:sdtPr>'
        "<w:sdtContent>" + _p("<w:t>CLÁUSULA 12</w:t><w:tab/><w:t>14</w:t>") + "</w:sdtContent>"
        "</w:sdt>"
    )
    assert _texto(_docx(indice + _p("<w:t>CLÁUSULA 12</w:t>"))) == "CLÁUSULA 12"


def test_la_tabulacion_posicional_y_las_formulas_son_texto() -> None:
    ns_m = 'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"'
    parrafo = (
        f"<w:p {ns_m}><w:r><w:t>Cláusula 5</w:t><w:ptab/><w:t>12</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> Fórmula: </w:t></w:r>'
        "<m:oMath><m:r><m:t>P=Pmax*(Omin/Oi)</m:t></m:r></m:oMath></w:p>"
    )
    assert _texto(_docx(parrafo)) == "Cláusula 5\t12 Fórmula: P=Pmax*(Omin/Oi)"
