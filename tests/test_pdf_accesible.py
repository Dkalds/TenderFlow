"""Accesibilidad de los PDFs que genera el producto.

Lo que se puede comprobar sin un validador PDF/UA: que cada documento declara
su idioma, que lleva título y autor, que el visor mostrará el título en vez
del nombre del fichero, que el contenido va etiquetado (árbol de estructura y
``MarkInfo``) y que el XMP declara PDF/UA-1. Que la estructura sea *buena*
(orden de lectura, encabezados) lo impone Typst al compilar con ``ua-1``: si
una plantilla lo rompe, no hay PDF.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest
from pypdf import PdfReader

from services.ficha_pdf import BloqueFicha, FichaOportunidad, construir_pdf
from services.pdf_tabular import construir_pdf_secciones, construir_pdf_tabular
from services.rag.guion_oferta import GuionOferta, a_pdf

ROWS = [{"Órgano": "Ayuntamiento de Cádiz", "Importe": "1.200 €"}]


def _tabla(title: str) -> bytes:
    return construir_pdf_tabular(ROWS, title)


def _secciones() -> bytes:
    return construir_pdf_secciones(
        "Informe semanal", [(None, ROWS)], subtitulo="Últimos 7 días", pie="Fin"
    )


def _ficha() -> bytes:
    return construir_pdf(
        FichaOportunidad(
            titulo="Servicios SAP",
            subtitulo="Oportunidad #1",
            bloques=[BloqueFicha(titulo="Órgano", filas=[("Órgano", "Ayuntamiento")])],
        )
    )


def _guion() -> bytes:
    return a_pdf(GuionOferta(licitacion_id="EXP-1"))


GENERADORES: dict[str, Callable[[], bytes]] = {
    "tabular": lambda: _tabla("Licitaciones abiertas"),
    "secciones": _secciones,
    "ficha": _ficha,
    "guion": _guion,
}


@pytest.fixture(params=sorted(GENERADORES), ids=sorted(GENERADORES))
def pdf(request: pytest.FixtureRequest) -> bytes:
    return GENERADORES[request.param]()


def _raiz(pdf: bytes) -> object:
    return PdfReader(io.BytesIO(pdf)).trailer["/Root"]


class TestIdioma:
    def test_declara_el_idioma_del_documento(self, pdf: bytes) -> None:
        """Sin `/Lang` un lector de pantalla no sabe en qué idioma leer."""
        assert _raiz(pdf).get("/Lang") == "es-ES"

    def test_el_visor_muestra_el_titulo_y_no_el_fichero(self, pdf: bytes) -> None:
        preferencias = _raiz(pdf)["/ViewerPreferences"].get_object()
        assert bool(preferencias["/DisplayDocTitle"])


class TestMetadatos:
    def test_todos_los_documentos_llevan_titulo(self, pdf: bytes) -> None:
        assert PdfReader(io.BytesIO(pdf)).metadata.title

    def test_el_pdf_tabular_declara_su_universo(self) -> None:
        assert PdfReader(io.BytesIO(_secciones())).metadata.subject == "Últimos 7 días"

    def test_el_autor_es_el_producto(self, pdf: bytes) -> None:
        assert PdfReader(io.BytesIO(pdf)).metadata.author == "TenderFlow"

    def test_la_ficha_se_titula_con_la_oportunidad(self) -> None:
        metadatos = PdfReader(io.BytesIO(_ficha())).metadata
        assert metadatos.title == "Servicios SAP"
        assert metadatos.subject == "Oportunidad #1"


class TestEtiquetado:
    def test_el_contenido_va_etiquetado(self, pdf: bytes) -> None:
        """Sin árbol de estructura el lector de pantalla no tiene orden de lectura."""
        raiz = _raiz(pdf)
        assert "/StructTreeRoot" in raiz
        assert bool(raiz["/MarkInfo"]["/Marked"])

    def test_declara_pdf_ua_1(self, pdf: bytes) -> None:
        xmp = _raiz(pdf)["/Metadata"].get_object().get_data().decode("utf-8")
        assert "pdfuaid:part" in xmp
        assert "1" in xmp.split("pdfuaid:part", 1)[1][:20]


class TestDatosNoMarcado:
    def test_el_texto_de_terceros_sale_literal(self) -> None:
        """Un título de la fuente con sintaxis de Typst o HTML no se interpreta."""
        titulo = 'Lote #1 *SAP* <img src="/etc/passwd"/> = x $y$'
        pdf = construir_pdf(FichaOportunidad(titulo=titulo, subtitulo="s", bloques=[]))
        texto = PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or ""
        assert "#1 *SAP*" in texto
        assert '<img src="/etc/passwd"/>' in texto


#: Lo que la fuente embebida no tiene y llega de verdad: emoji en un nombre de
#: organización, la viñeta de Word (U+F0B7) en el texto de un pliego, un
#: nombre de empresa en CJK y un carácter de control del extractor. El
#: tailandés no lo quita el prefiltro: ejercita el reintento por carácter.
SIN_GLIFO = "Acme 😀  punto 北京 Ltd ctrl\x07x ไทย"


def _con_texto(texto: str) -> dict[str, Callable[[], bytes]]:
    from services.rag.guion_oferta import GuionCriterio, PuntoGuion

    return {
        "tabular": lambda: construir_pdf_tabular([{"Empresa": texto}], texto),
        "ficha": lambda: construir_pdf(
            FichaOportunidad(
                titulo=texto, subtitulo=texto, bloques=[BloqueFicha(texto, [(texto, texto)])]
            )
        ),
        "guion": lambda: a_pdf(
            GuionOferta(
                licitacion_id="EXP-1",
                criterios=[
                    GuionCriterio(criterio=texto, puntos=[PuntoGuion(texto=texto, sin_base=True)])
                ],
            )
        ),
    }


class TestCaracteresSinGlifo:
    @pytest.mark.parametrize("generador", ["tabular", "ficha", "guion"])
    def test_un_caracter_sin_glifo_no_tumba_el_pdf(self, generador: str) -> None:
        """PDF/UA-1 prohíbe `.notdef` y Typst no genera el PDF: se sustituye."""
        pdf = _con_texto(SIN_GLIFO)[generador]()
        texto = " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
        assert "Acme" in texto and "Ltd" in texto
        assert "ctrlx" in texto  # el de control se quita, no se sustituye
        assert "?" in texto


class TestContenido:
    def test_el_pdf_tabular_conserva_acentos_al_extraerlo(self) -> None:
        """Los metadatos no pueden costar el texto: `lang` es un extra, no un cambio."""
        texto = PdfReader(io.BytesIO(_tabla("Licitaciones"))).pages[0].extract_text() or ""
        assert "Ayuntamiento de Cádiz" in texto
