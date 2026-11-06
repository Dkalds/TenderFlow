"""Qué fallos de la ficha del pliego merecen un reintento y cuáles no.

En producción (2026-11-06) 15 de los 24 jobs ``ficha_pliego`` fallidos eran
«sin pliegos» o «PLACSP aún no lo ha publicado», reintentados tres veces con
backoff; y dos fichas de pliegos grandes fallaban con el JSON cortado por el
tope de tokens, que se corta igual al repetir. Sin BD ni red.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from llm.json_utils import RespuestaTruncada, extract_json_object
from services.rag import fact_sheet


def test_un_json_cortado_por_el_tope_se_distingue_de_uno_mal_escrito() -> None:
    cortado = '{"award_criteria": [{"name": "Precio", "weight": 40}, {"name": "Calid'
    with pytest.raises(RespuestaTruncada, match="tope de tokens"):
        extract_json_object(cortado)


def test_un_json_mal_escrito_pero_completo_no_es_truncado() -> None:
    with pytest.raises(ValueError) as exc:
        extract_json_object('{"a": 1 "b": 2}')
    assert not isinstance(exc.value, RespuestaTruncada)


def test_un_json_completo_con_texto_alrededor_se_sigue_aceptando() -> None:
    assert extract_json_object('Aquí va:\n```json\n{"a": 1}\n```') == {"a": 1}


@pytest.mark.parametrize(
    ("fetched", "reintentable"),
    [
        ({"skipped": 3}, True),  # el breaker de PLACSP está abierto: vuelve en minutos
        ({"attempted": 0}, False),  # no hay pliegos que leer
        ({"skipped_no_extra": 2}, False),  # falta el extractor del formato
        ({"skipped": 1, "error": 1}, False),
    ],
)
def test_sin_paginas_solo_reintenta_si_placsp_no_responde(
    fetched: dict[str, int], reintentable: bool
) -> None:
    with (
        patch("services.dedupe.expediente_del_pliego", side_effect=lambda x: x),
        patch.object(fact_sheet, "ensure_documents_ready", return_value=fetched),
        patch.object(fact_sheet, "DocumentosRepository") as repo,
        pytest.raises(fact_sheet.SinPaginasError) as exc,
    ):
        repo.return_value.list_pages_by_licitacion.return_value = []
        repo.return_value.list_by_licitacion.return_value = []
        fact_sheet.extract_fact_sheet_on_demand("EXP-1", model="m")

    assert exc.value.reintentable is reintentable


@pytest.mark.parametrize(
    ("error", "definitivo"),
    [
        (fact_sheet.SinPaginasError("sin pliegos", licitacion_id="EXP-1"), True),
        (
            fact_sheet.SinPaginasError("PLACSP caído", licitacion_id="EXP-1", reintentable=True),
            False,
        ),
        (RespuestaTruncada("cortada"), True),
        (ValueError("respuesta vacía del proveedor"), False),
        (RuntimeError("timeout"), False),
    ],
)
def test_la_extraccion_en_segundo_plano_dice_si_el_fallo_es_definitivo(
    error: Exception, definitivo: bool
) -> None:
    repo: Any = MagicMock()
    with (
        patch.object(fact_sheet, "extract_fact_sheet_on_demand", side_effect=error),
        patch.object(fact_sheet, "TenderFactSheetsRepository", return_value=repo),
        patch.object(fact_sheet, "clear_extraction_running"),
    ):
        assert fact_sheet.run_background_extraction("EXP-1", model="m") is definitivo
