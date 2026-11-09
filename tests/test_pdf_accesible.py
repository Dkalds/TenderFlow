"""Accesibilidad de los PDFs que genera el producto.

Lo que se puede comprobar sin un validador PDF/UA: que cada documento declara
su idioma, que lleva título y autor, y que el visor mostrará el título en vez
del nombre del fichero. El etiquetado de contenido (estructura, orden de
lectura) sigue sin hacerse y no se finge aquí.
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

    def test_el_autor_y_el_productor_son_el_producto(self, pdf: bytes) -> None:
        metadatos = PdfReader(io.BytesIO(pdf)).metadata
        assert metadatos.author == "TenderFlow"
        assert metadatos.creator == "TenderFlow"
        assert metadatos.producer == "TenderFlow"

    def test_la_ficha_se_titula_con_la_oportunidad(self) -> None:
        metadatos = PdfReader(io.BytesIO(_ficha())).metadata
        assert metadatos.title == "Servicios SAP"
        assert metadatos.subject == "Oportunidad #1"


class TestContenido:
    def test_el_pdf_tabular_conserva_acentos_al_extraerlo(self) -> None:
        """Los metadatos no pueden costar el texto: `lang` es un extra, no un cambio."""
        texto = PdfReader(io.BytesIO(_tabla("Licitaciones"))).pages[0].extract_text() or ""
        assert "Ayuntamiento de Cádiz" in texto
