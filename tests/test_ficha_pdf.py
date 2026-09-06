"""F2.7 — la ficha de oportunidad en PDF.

Lo que se prueba es la regla del papel: **un bloque sin datos se omite con
nota, no se rellena**. Un one-pager con guiones se lee como que el producto no
sabe nada; una nota que dice qué falta y por qué se lee como trazabilidad
(ADR-014 llevado al PDF).
"""

from __future__ import annotations

import io

from pypdf import PdfReader

from services.ficha_pdf import BloqueFicha, FichaOportunidad, construir_pdf


def _pdf(*bloques: BloqueFicha) -> bytes:
    return construir_pdf(
        FichaOportunidad(titulo="Servicios SAP", subtitulo="Oportunidad #1", bloques=list(bloques))
    )


def _texto(pdf: bytes) -> str:
    """El texto que un lector ve, extraído con `pypdf` (ya es dependencia).

    Buscar literales en los bytes crudos no vale: reportlab comprime el stream
    de contenido, así que un `assert b"Sin estimación" in pdf` pasa o falla por
    razones que no tienen que ver con lo que el PDF dice.
    """
    paginas = [page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages]
    return chr(10).join(paginas)


class TestEstructura:
    def test_genera_un_pdf(self) -> None:
        pdf = _pdf(BloqueFicha(titulo="Expediente", filas=[("Órgano", "Ayuntamiento")]))
        assert pdf.startswith(b"%PDF-")
        assert pdf.rstrip().endswith(b"%%EOF")

    def test_sin_bloques_sigue_siendo_un_pdf_valido(self) -> None:
        """Una oportunidad recién creada no tiene casi nada que contar."""
        pdf = _pdf()
        assert pdf.startswith(b"%PDF-")

    def test_un_bloque_con_filas_no_esta_vacio(self) -> None:
        bloque = BloqueFicha(titulo="Oferta", filas=[("Precio", "100 €")])
        assert not bloque.vacio

    def test_un_bloque_sin_filas_esta_vacio(self) -> None:
        assert BloqueFicha(titulo="Oferta").vacio

    def test_el_titulo_del_documento_es_el_de_la_oportunidad(self) -> None:
        pdf = construir_pdf(FichaOportunidad(titulo="Mantenimiento SAP", subtitulo="x", bloques=[]))
        assert "Mantenimiento SAP" in _texto(pdf)


class TestNoRellenaHuecos:
    def test_el_bloque_vacio_lleva_su_nota(self) -> None:
        pdf = _pdf(
            BloqueFicha(
                titulo="Fecha prevista de adjudicación",
                nota_vacio="Sin estimación: el órgano no tiene adjudicaciones suficientes.",
            )
        )
        assert "Sin estimación" in _texto(pdf)

    def test_el_bloque_vacio_sin_nota_lo_dice_igual(self) -> None:
        """Nunca un bloque en blanco: el hueco silencioso se lee como un cero."""
        pdf = _pdf(BloqueFicha(titulo="Oferta"))
        assert "Sin datos suficientes" in _texto(pdf)

    def test_la_procedencia_acompana_a_la_cifra(self) -> None:
        pdf = _pdf(
            BloqueFicha(
                titulo="Fecha prevista",
                filas=[("Estimación", "2026-11-30")],
                procedencia="Sobre 12 adjudicaciones de los últimos 24 meses.",
            )
        )
        assert "24 meses" in _texto(pdf)


class TestValoresDificiles:
    def test_none_se_pinta_como_raya_y_no_como_none(self) -> None:
        pdf = _pdf(BloqueFicha(titulo="Oferta", filas=[("Precio", None)]))  # type: ignore[list-item]
        texto = _texto(pdf)
        assert "None" not in texto
        assert "—" in texto

    def test_cadena_vacia_se_pinta_como_raya(self) -> None:
        pdf = _pdf(BloqueFicha(titulo="Oferta", filas=[("Precio", "   ")]))
        assert "—" in _texto(pdf)

    def test_un_titulo_larguisimo_no_rompe_la_maqueta(self) -> None:
        """Un título de 400 caracteres reventaba la tabla en vez de envolverse."""
        pdf = _pdf(BloqueFicha(titulo="Expediente", filas=[("Título", "x" * 400)]))
        assert pdf.startswith(b"%PDF-")
        # Recortado, no impreso entero.
        assert "x" * 300 not in _texto(pdf)
