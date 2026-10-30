"""El núcleo de la extracción de la ficha, sin base de datos.

``extraer_hechos`` es lo que el eval de la ficha ejecuta sobre los casos del
golden: tiene que ser el mismo camino que producción —selector, prompt,
validación de citas— y no puede abrir una conexión, porque el eval arranca sin
``DATABASE_URL``.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

import services.rag.fact_sheet as fs
from services.rag.fact_sheet import extraer_hechos

_TEXTO = "El criterio precio tendrá una ponderación del 60 por ciento."
_CITA = "criterio precio tendrá una ponderación del 60 por ciento"


def _paginas(texto: str = _TEXTO) -> list[dict[str, Any]]:
    return [
        {
            "documento_id": 7,
            "page_number": 1,
            "tipo": "legal",
            "filename": "pcap.pdf",
            "texto": texto,
            "start_offset": 0,
            "end_offset": len(texto),
            "ocr": False,
        }
    ]


def _criterio(*, cita: str = _CITA, con_nombre: bool = True) -> dict[str, Any]:
    criterio: dict[str, Any] = {
        "description": "Criterio económico",
        "weight_pct": 60,
        "criterion_type": "price",
        "confidence": 0.95,
        "evidence": [{"documento_id": 7, "page_number": 1, "quote": cita}],
    }
    if con_nombre:
        criterio["name"] = "Precio"
    return criterio


def _respuesta(*criterios: dict[str, Any]) -> Any:
    return iter([json.dumps({"award_criteria": list(criterios)})])


def test_extraer_hechos_no_toca_los_repositorios() -> None:
    paginas = _paginas()
    sin_bd = AssertionError("el núcleo de la extracción no puede usar un repositorio")

    with (
        patch("services.rag.fact_sheet.DocumentosRepository", side_effect=sin_bd),
        patch("services.rag.fact_sheet.TenderFactSheetsRepository", side_effect=sin_bd),
        patch("services.rag.fact_sheet.stream_llm_response", return_value=_respuesta(_criterio())),
    ):
        resultado = extraer_hechos(paginas, licitacion_id="EXP-1", model="modelo-x")

    assert len(resultado.facts.award_criteria) == 1
    assert resultado.facts.award_criteria[0].weight_pct == 60
    assert (resultado.invalidos, resultado.inverificables) == (0, 0)
    assert resultado.seleccionadas == paginas


def test_extraer_hechos_cuenta_los_dos_tipos_de_descarte() -> None:
    sin_nombre = _criterio(con_nombre=False)
    cita_inventada = _criterio(cita="esta frase no aparece en ninguna página del pliego")

    with patch(
        "services.rag.fact_sheet.stream_llm_response",
        return_value=_respuesta(sin_nombre, cita_inventada, _criterio()),
    ):
        resultado = extraer_hechos(_paginas(), licitacion_id="EXP-1", model="modelo-x")

    assert (resultado.invalidos, resultado.inverificables) == (1, 1)
    assert len(resultado.facts.award_criteria) == 1


def test_extraer_hechos_sin_texto_lanza_value_error() -> None:
    with (
        patch("services.rag.fact_sheet.stream_llm_response") as llm,
        pytest.raises(ValueError, match="No hay texto por página"),
    ):
        extraer_hechos(_paginas(texto="   "), licitacion_id="EXP-1", model="modelo-x")

    llm.assert_not_called()


def test_respuesta_vacia_del_modelo_lanza_value_error() -> None:
    with (
        patch("services.rag.fact_sheet.stream_llm_response", return_value=iter([])),
        pytest.raises(ValueError, match="respuesta vacía"),
    ):
        extraer_hechos(_paginas(), licitacion_id="EXP-1", model="modelo-x")


# ── Pasada de documentos a presentar (v7) ───────────────────────────────────

_TEXTO_SOBRES = (
    "Sobre nº1: Documentación General. Contendrá el DEUC. En caso de UTE se aportará "
    "el compromiso de constitución de la UTE."
)


def _paginas_con_sobres() -> list[dict[str, Any]]:
    return [
        *_paginas(),
        {
            "documento_id": 7,
            "page_number": 6,
            "tipo": "legal",
            "filename": "pcap.pdf",
            "texto": _TEXTO_SOBRES,
            "start_offset": 1000,
            "end_offset": 1000 + len(_TEXTO_SOBRES),
            "ocr": False,
        },
    ]


def _documento(nombre: str, cita: str, sobre: str = "sobre_a") -> dict[str, Any]:
    return {
        "description": f"Exige {nombre}",
        "confidence": 0.9,
        "evidence": [{"documento_id": 7, "page_number": 6, "quote": cita}],
        "name": nombre,
        "scope": sobre,
        "subsanable": None,
    }


def _llamadas(*respuestas: dict[str, Any]) -> list[Any]:
    return [iter([json.dumps(r)]) for r in respuestas]


def test_la_pasada_de_documentos_va_aparte_y_se_fusiona_sin_repetir() -> None:
    general = {
        "award_criteria": [_criterio()],
        "required_documents": [_documento("deuc ", "Contendrá el DEUC", "otro")],
    }
    dedicada = {
        "required_documents": [
            _documento("DEUC", "Contendrá el DEUC"),
            _documento("Compromiso de constitución de UTE", "compromiso de constitución de la UTE"),
        ]
    }

    with patch(
        "services.rag.fact_sheet.stream_llm_response", side_effect=_llamadas(general, dedicada)
    ) as llm:
        resultado = extraer_hechos(_paginas_con_sobres(), licitacion_id="EXP-1", model="m")

    assert llm.call_count == 2
    segunda = llm.call_args_list[1].kwargs
    assert segunda["question"] == fs._DOCUMENTS_QUESTION
    assert [c["page_number"] for c in segunda["docs"][0]["chunks"]] == [6]
    documentos = resultado.facts.required_documents
    # El DEUC de la pasada dedicada manda (con su sobre); el de la general no se repite.
    assert [(d.name, d.scope) for d in documentos] == [
        ("DEUC", "sobre_a"),
        ("Compromiso de constitución de UTE", "sobre_a"),
    ]
    assert len(resultado.facts.award_criteria) == 1


def test_si_la_pasada_de_documentos_falla_queda_la_ficha_general() -> None:
    general = {"required_documents": [_documento("DEUC", "Contendrá el DEUC")]}

    with patch(
        "services.rag.fact_sheet.stream_llm_response",
        side_effect=[iter([json.dumps(general)]), iter([])],
    ):
        resultado = extraer_hechos(_paginas_con_sobres(), licitacion_id="EXP-1", model="m")

    assert [d.name for d in resultado.facts.required_documents] == ["DEUC"]


def test_sin_paginas_de_documentacion_no_hay_segunda_llamada() -> None:
    with patch(
        "services.rag.fact_sheet.stream_llm_response", return_value=_respuesta(_criterio())
    ) as llm:
        extraer_hechos(_paginas(), licitacion_id="EXP-1", model="m")

    assert llm.call_count == 1


def test_los_descartes_de_la_pasada_de_documentos_cuentan() -> None:
    dedicada = {"required_documents": [_documento("Inventado", "frase que no está en el pliego")]}

    with patch(
        "services.rag.fact_sheet.stream_llm_response",
        side_effect=_llamadas({"award_criteria": [_criterio()]}, dedicada),
    ):
        resultado = extraer_hechos(_paginas_con_sobres(), licitacion_id="EXP-1", model="m")

    assert resultado.inverificables == 1
    assert resultado.facts.required_documents == []


def test_la_pasada_de_documentos_ordena_por_terminos_y_respeta_su_presupuesto() -> None:
    def pagina(n: int, texto: str) -> dict[str, Any]:
        return {"documento_id": 7, "page_number": n, "tipo": "legal", "texto": texto}

    larga = "DEUC " + "x" * fs._DOC_MAX_CONTEXT_CHARS
    paginas = [
        pagina(1, _TEXTO),
        pagina(2, "declaración responsable"),
        pagina(3, "Sobre nº 1: DEUC y declaración responsable."),
        pagina(4, larga),
    ]

    with patch(
        "services.rag.fact_sheet.stream_llm_response",
        side_effect=_llamadas({"award_criteria": [_criterio()]}, {"required_documents": []}),
    ) as llm:
        extraer_hechos(paginas, licitacion_id="EXP-1", model="m")

    chunks = llm.call_args_list[1].kwargs["docs"][0]["chunks"]
    # La 1 no habla de documentación ni entra como portada; la 4 no cabe
    # después de la 3, que puntúa más.
    assert [c["page_number"] for c in chunks] == [2, 3]


def test_la_pregunta_de_documentos_cabe_en_el_limite() -> None:
    from llm.client import MAX_INTERNAL_QUESTION_LEN

    assert len(fs._DOCUMENTS_QUESTION) <= MAX_INTERNAL_QUESTION_LEN
