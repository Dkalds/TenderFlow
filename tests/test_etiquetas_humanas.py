"""Qué etiqueta de familia sale de una fila de `ml_feedback` (2026-09-27).

`relevante` significó «es SAP» hasta el plan de tres niveles y significa «es
TI» desde `revision_ti`. Una fila vieja con `relevante=0` y sin tecnología no
dice que no haya familia: dice que no era SAP. Tratarla como negativo de todas
las familias entrenaba 45 negativos falsos.
"""

from __future__ import annotations

import pytest

from db.repositories.licitaciones import etiqueta_humana


@pytest.mark.parametrize(
    ("source", "relevante", "tecnologia", "secundarias", "esperada"),
    [
        ("revision_ti", 1, "ERP", '["SAP"]', "ERP,SAP"),
        ("revision_ti", 1, None, None, ""),  # TI sin familia: negativo de todas
        ("revision_ti", 0, None, None, ""),  # no es TI: negativo de todas
        ("human", 1, "SAP", None, "SAP"),  # heredada con tecnología: vale
        ("human", 0, None, None, None),  # heredada sin tecnología: no se pronuncia
        ("human", 0, "ORACLE", None, "ORACLE"),
    ],
)
def test_etiqueta_humana(source, relevante, tecnologia, secundarias, esperada) -> None:
    assert etiqueta_humana(source, relevante, tecnologia, secundarias) == esperada
