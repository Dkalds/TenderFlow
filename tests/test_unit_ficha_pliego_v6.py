"""Ficha del pliego v6 y cobertura de documentos: las causas medidas el 2026-09-28.

Cada test fija una de las causas por las que, en producción, la ficha salía
vacía o el pliego no llegaba a leerse. Sin BD: son las funciones puras.
"""

from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import patch

import pytest

from services.rag import fact_sheet as fs
from shared.tender_facts import EvidenceRef

PAGINA_21 = (
    "CRITERIO: Equipo de implantación, puesta en marcha y migración, hasta 12 puntos. "
    "Se valorará la experiencia del equipo."
)
PAGINA_22 = (
    "(*) PUNTUACIÓN: \n \nPara determinar la puntuación económica de una oferta (PE) se "
    "procederá del siguiente modo: \n•  Se asignarán 70 puntos a la oferta más económica "
    "( OEmax) y que no haya sido rechazada. \n•  Se asignarán 0 puntos al presupuesto de "
    "licitación  (PL)."
)


def _indice(*paginas: tuple[int, int, str]) -> dict[tuple[int, int], dict[str, Any]]:
    return {
        (doc, num): {"documento_id": doc, "page_number": num, "texto": texto, "start_offset": 0}
        for doc, num, texto in paginas
    }


class TestVerificacionDeCitas:
    def test_los_blancos_del_extractor_de_pdf_no_invalidan_la_cita(self):
        """«( OEmax)» en la página y «(OEmax)» en la cita: la fórmula de precio
        de un pliego real se descartaba por ese espacio."""
        cita = EvidenceRef(
            documento_id=1,
            page_number=22,
            quote="Se asignarán 70 puntos a la oferta más económica (OEmax) y que no haya "
            "sido rechazada.",
        )
        assert fs._validated_evidence(cita, _indice((1, 22, PAGINA_22))) is not None

    def test_una_cita_abreviada_con_elipsis_vale_si_cada_trozo_es_literal(self):
        cita = EvidenceRef(
            documento_id=1,
            page_number=22,
            quote="Para determinar la puntuación económica de una oferta (PE)... "
            "Se asignarán 0 puntos al presupuesto de licitación (PL).",
        )
        assert fs._validated_evidence(cita, _indice((1, 22, PAGINA_22))) is not None

    def test_la_elipsis_no_deja_pasar_texto_inventado(self):
        cita = EvidenceRef(
            documento_id=1,
            page_number=22,
            quote="Para determinar la puntuación económica de una oferta (PE)... "
            "[fórmula implícita de proporcional inversa]",
        )
        assert fs._validated_evidence(cita, _indice((1, 22, PAGINA_22))) is None

    def test_los_trozos_tienen_que_ir_en_orden(self):
        cita = EvidenceRef(
            documento_id=1,
            page_number=22,
            quote="Se asignarán 0 puntos al presupuesto de licitación (PL)... "
            "Para determinar la puntuación económica de una oferta (PE)",
        )
        assert fs._validated_evidence(cita, _indice((1, 22, PAGINA_22))) is None

    def test_una_elipsis_entre_trozos_triviales_no_prueba_nada(self):
        cita = EvidenceRef(documento_id=1, page_number=22, quote="de la... se... oferta")
        assert fs._validated_evidence(cita, _indice((1, 22, PAGINA_22))) is None

    def test_se_corrige_la_pagina_contigua_del_mismo_documento(self):
        cita = EvidenceRef(
            documento_id=1,
            page_number=22,
            quote="CRITERIO: Equipo de implantación, puesta en marcha y migración, hasta 12 puntos.",
        )
        validada = fs._validated_evidence(cita, _indice((1, 21, PAGINA_21), (1, 22, PAGINA_22)))
        assert validada is not None
        assert validada.page_number == 21
        assert validada.start_offset == 0

    def test_no_se_busca_en_otro_documento(self):
        """La misma frase en el PCAP y en el PPT puede decir cosas distintas."""
        cita = EvidenceRef(
            documento_id=1,
            page_number=1,
            quote="CRITERIO: Equipo de implantación, puesta en marcha y migración, hasta 12 puntos.",
        )
        assert (
            fs._validated_evidence(cita, _indice((1, 1, "otra cosa"), (2, 21, PAGINA_21))) is None
        )


class TestNormalizacionDeHechos:
    def _hecho(self, **extra: Any) -> dict[str, Any]:
        return {"description": "Garantía definitiva", "confidence": 0.8, **extra}

    def test_una_cita_larga_se_recorta_en_vez_de_tirar_el_hecho(self):
        payload = {
            "guarantees": [
                self._hecho(evidence=[{"documento_id": 1, "page_number": 1, "quote": "a" * 900}])
            ]
        }
        facts, invalidos = fs._parse_facts(payload)
        assert invalidos == 0
        assert len(facts.guarantees[0].evidence[0].quote) == fs._MAX_QUOTE_CHARS

    def test_evidence_como_objeto_suelto_se_envuelve(self):
        payload = {
            "guarantees": [
                self._hecho(
                    evidence={"documento_id": 1, "page_number": 1, "quote": "cinco por ciento"}
                )
            ]
        }
        facts, invalidos = fs._parse_facts(payload)
        assert invalidos == 0
        assert facts.guarantees[0].evidence[0].quote == "cinco por ciento"

    def test_la_prosa_en_params_no_tira_la_formula(self):
        payload = {
            "price_formula": [
                self._hecho(
                    formula_type="con_umbral_temeridad",
                    params={"OEM": "oferta económica más baja", "umbral": "0,25", "tramos": 3},
                )
            ]
        }
        facts, invalidos = fs._parse_facts(payload)
        assert invalidos == 0
        assert facts.price_formula[0].params == {"umbral": 0.25, "tramos": 3.0}

    def test_sin_confidence_el_hecho_se_descarta_y_se_dice_por_que(self):
        """No se inventa una confianza que el modelo no dio; se registra el
        motivo, que hasta v6 era invisible (`invalid=14` a secas)."""
        payload = {"guarantees": [{"description": "Garantía", "evidence": []}]}
        with patch.object(fs.log, "info") as info:
            facts, invalidos = fs._parse_facts(payload)
        assert invalidos == 1
        assert facts.guarantees == []
        motivos = info.call_args.kwargs["motivos"]
        assert motivos == {"guarantees.confidence:missing": 1}


class TestSeleccionDePaginas:
    def test_la_portada_de_un_anexo_no_se_reserva(self):
        """El DEUC se comía presupuesto antes que las páginas puntuadas."""
        # Con la regla anterior, portada del PCAP (14) + portada del anexo (38)
        # dejaban sin sitio a la página de la fórmula (40) en un presupuesto de 60.
        relleno = "texto sin términos " * 2
        paginas = [
            {"documento_id": 1, "page_number": 1, "tipo": "legal", "texto": "Cuadro resumen"},
            {"documento_id": 1, "page_number": 2, "tipo": "legal", "texto": "fórmula " * 5},
            {"documento_id": 2, "page_number": 1, "tipo": "additional", "texto": relleno},
        ]
        with patch.object(fs, "_MAX_CONTEXT_CHARS", 60):
            elegidas = fs._select_pages(paginas)
        claves = [(p["documento_id"], p["page_number"]) for p in elegidas]
        assert claves == [(1, 1), (1, 2)]

    def test_la_formula_de_precio_puntua(self):
        assert fs._page_score({"texto": "La fórmula de la oferta económica"}) >= 2


class TestRespuestaVacia:
    def test_un_stream_vacio_se_dice_como_tal_y_no_como_json_invalido(self):
        pagina = {
            "documento_id": 1,
            "page_number": 1,
            "texto": "pliego",
            "tipo": "legal",
            "filename": "PCAP.pdf",
        }
        with (
            patch.object(fs, "DocumentosRepository") as docs,
            patch.object(fs, "TenderFactSheetsRepository") as fichas,
            patch.object(fs, "stream_llm_response", return_value=iter([])),
        ):
            docs.return_value.list_pages_by_licitacion.return_value = [pagina]
            with pytest.raises(ValueError, match="respuesta vacía"):
                fs.extract_fact_sheet("EXP-1", model="gpt-4o-mini")
        persistida = fichas.return_value.upsert.call_args.kwargs
        assert persistida["status"] == "failed"
        assert "respuesta vacía" in persistida["error_detail"]


class TestReintentoDelProveedor:
    def test_la_saturacion_sin_codigo_http_se_reintenta(self):
        """NIM manda «Service temporarily overloaded» como evento SSE, sin
        ``status_code``: no se reintentaba y la ficha caía en ~250 ms."""
        from llm.providers.openai_provider import _is_retryable

        class APIError(Exception):
            pass

        assert _is_retryable(APIError("Service temporarily overloaded"))
        assert not _is_retryable(APIError("Invalid request: bad parameter"))


def _zip(entradas: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archivo:
        for nombre, datos in entradas.items():
            archivo.writestr(nombre, datos)
    return buffer.getvalue()


class TestFormatoPorContenido:
    def test_docx_con_content_type_mal_escrito_se_reconoce(self):
        """1.964 documentos de producción caían en `unsupported` por el guion
        que falta en el tipo que manda PLACSP."""
        from scraper.document_fetcher import CONTENT_TYPE_DOCX, _resolver_content_type

        malo = "application/vnd.openxmlformatsofficedocument.wordprocessingml.document"
        docx = _zip({"[Content_Types].xml": b"<x/>", "word/document.xml": b"<w/>"})
        assert _resolver_content_type(docx, malo) == CONTENT_TYPE_DOCX

    def test_pdf_como_octet_stream_se_reconoce(self):
        from scraper.document_fetcher import CONTENT_TYPE_PDF, _resolver_content_type

        assert _resolver_content_type(b"%PDF-1.7\n...", "application/octet-stream") == (
            CONTENT_TYPE_PDF
        )

    def test_odt_y_zip_real(self):
        from scraper.document_fetcher import (
            CONTENT_TYPE_ODT,
            CONTENT_TYPE_ZIP,
            _resolver_content_type,
        )

        odt = _zip({"mimetype": CONTENT_TYPE_ODT.encode(), "content.xml": b"<x/>"})
        assert _resolver_content_type(odt, "application/octet-stream") == CONTENT_TYPE_ODT
        expediente = _zip({"PCAP.pdf": b"%PDF-1.4", "PPT.pdf": b"%PDF-1.4"})
        assert _resolver_content_type(expediente, "application/x-zip-compressed") == (
            CONTENT_TYPE_ZIP
        )

    def test_una_hoja_de_calculo_conserva_su_tipo_y_sigue_sin_soporte(self):
        from scraper.document_fetcher import _resolver_content_type

        xlsx_tipo = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        xlsx = _zip({"xl/workbook.xml": b"<x/>"})
        assert _resolver_content_type(xlsx, xlsx_tipo) == xlsx_tipo

    def test_sin_firma_manda_el_tipo_declarado(self):
        from scraper.document_fetcher import CONTENT_TYPE_TEXT, _resolver_content_type

        assert _resolver_content_type(b"texto plano", CONTENT_TYPE_TEXT) == CONTENT_TYPE_TEXT
        assert _resolver_content_type(b"???", None) is None
