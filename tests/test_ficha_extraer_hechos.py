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
