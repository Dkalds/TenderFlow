"""F2.6 — el guion de la oferta en PDF, sin volver a llamar al LLM.

El guion se exportaba solo a Markdown desde el navegador; el PDF no tenía ruta
en el backend. Dos cosas se fijan aquí: que el PDF sale **del guion ya
generado** —la descarga nunca gasta presupuesto— y que la generación deja ese
guion cacheado por firma de ficha y páginas, que es lo que el plan pedía y lo
que el frontend ya daba por hecho («regenerar sin que cambie el pliego no
cuesta»).
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from pypdf import PdfReader

from services.rag import guion_oferta as mod
from services.rag.guion_oferta import (
    GuionCriterio,
    GuionOferta,
    PuntoGuion,
    a_pdf,
    generar_guion,
    guion_generado,
    guion_pdf,
)
from shared.tender_facts import EvidenceRef

_PAGINAS = [
    {"documento_id": 7, "page_number": 3, "tipo": "technical", "filename": "ppt.pdf", "texto": "x"}
]


def _guion() -> GuionOferta:
    return GuionOferta(
        licitacion_id="EXP-1",
        firma="abc123",
        criterios=[
            GuionCriterio(
                criterio="Memoria técnica <b>",
                peso_pct=40,
                puntos=[
                    PuntoGuion(
                        texto="Describir la metodología & el plan.",
                        evidencia=[EvidenceRef(documento_id=7, page_number=3, quote="metodología")],
                    ),
                    PuntoGuion(texto="Proponer un piloto.", sin_base=True),
                ],
            )
        ],
    )


def _texto(pdf: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


@pytest.fixture(autouse=True)
def _cache_limpia() -> Any:
    from shared.cache import get_cache, reset_cache

    get_cache(mod.GUION_CACHE_NAMESPACE).clear()
    yield
    reset_cache(mod.GUION_CACHE_NAMESPACE)


class TestPdf:
    def test_es_un_pdf_con_el_esquema(self) -> None:
        pdf = a_pdf(_guion(), {7: "pliego-tecnico.pdf"})
        assert pdf.startswith(b"%PDF")
        texto = _texto(pdf)
        assert "Memoria técnica <b> (40 puntos)" in texto
        assert "Describir la metodología & el plan." in texto
        assert "pliego-tecnico.pdf p. 3" in texto
        assert "sin base en el pliego" in texto

    def test_sin_nombre_cita_el_id(self) -> None:
        assert "doc 7 p. 3" in _texto(a_pdf(_guion()))

    def test_sin_guion_lo_dice(self) -> None:
        pdf = a_pdf(GuionOferta(licitacion_id="EXP-1", sin_guion="No hay criterios."))
        assert "No hay criterios." in _texto(pdf)


def _ficha() -> Any:
    facts = SimpleNamespace(award_criteria=["precio"], model_dump_json=lambda: '{"a":1}')
    return SimpleNamespace(facts=facts)


def _respuesta_llm(*_a: Any, **_k: Any) -> Any:
    yield json.dumps(
        {
            "criterios": [
                {
                    "criterio": "Memoria",
                    "peso_pct": 40,
                    "puntos": [
                        {
                            "texto": "Describir el plan.",
                            "evidencia": [
                                {"documento_id": 7, "page_number": 3, "quote": "plan de trabajo"}
                            ],
                        }
                    ],
                }
            ]
        }
    )


class TestCacheYDescarga:
    def _parches(self) -> Any:
        from contextlib import ExitStack

        pila = ExitStack()
        pila.enter_context(patch("services.rag.fact_sheet.get_fact_sheet", return_value=_ficha()))
        pila.enter_context(
            patch(
                "db.repositories.documentos.DocumentosRepository.list_pages_by_licitacion",
                return_value=_PAGINAS,
            )
        )
        pila.enter_context(
            patch(
                "db.repositories.documentos.DocumentosRepository.list_by_licitacion",
                return_value=[{"id": 7, "filename": "ppt.pdf", "tipo": "technical"}],
            )
        )
        return pila

    def test_sin_generar_no_hay_pdf_ni_llm(self) -> None:
        with (
            self._parches(),
            patch("llm.client.stream_llm_response", side_effect=AssertionError("LLM")),
        ):
            assert guion_generado("EXP-1") is None
            assert guion_pdf("EXP-1") is None

    def test_generar_deja_el_guion_para_la_descarga(self) -> None:
        with self._parches():
            with patch("llm.client.stream_llm_response", side_effect=_respuesta_llm) as llm:
                generado = generar_guion("EXP-1")
                # Segunda petición con el mismo pliego: de la caché, sin LLM.
                assert generar_guion("EXP-1") == generado
            assert llm.call_count == 1
            with patch("llm.client.stream_llm_response", side_effect=AssertionError("LLM")):
                assert guion_generado("EXP-1") == generado
                pdf = guion_pdf("EXP-1")
        assert pdf is not None
        assert "ppt.pdf p. 3" in _texto(pdf)

    def test_si_cambia_el_pliego_la_descarga_no_sirve_el_viejo(self) -> None:
        with self._parches(), patch("llm.client.stream_llm_response", side_effect=_respuesta_llm):
            generar_guion("EXP-1")
        otras = [{**_PAGINAS[0], "texto": "pliego nuevo"}]
        with (
            patch("services.rag.fact_sheet.get_fact_sheet", return_value=_ficha()),
            patch(
                "db.repositories.documentos.DocumentosRepository.list_pages_by_licitacion",
                return_value=otras,
            ),
        ):
            assert guion_generado("EXP-1") is None

    def test_un_guion_vacio_no_se_cachea(self) -> None:
        def _roto(*_a: Any, **_k: Any) -> Any:
            yield "no es json"

        with self._parches(), patch("llm.client.stream_llm_response", side_effect=_roto):
            generar_guion("EXP-1")
            assert guion_generado("EXP-1") is None


class TestRuta:
    def test_declara_pdf_y_404(self) -> None:
        from api.app import app

        operacion = app.openapi()["paths"]["/api/v1/licitaciones/{id_externo}/guion.pdf"]["get"]
        assert "application/pdf" in operacion["responses"]["200"]["content"]
        assert "404" in operacion["responses"]
