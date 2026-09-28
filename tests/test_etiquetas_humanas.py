"""Qué etiqueta de familia sale de una fila de `ml_feedback` (2026-09-27).

`relevante` significó «es SAP» hasta el plan de tres niveles y significa «es
TI» desde `revision_ti`. Una fila vieja sin tecnología no dice que no haya
familia, sea cual sea su `relevante`: dice que era (o no era) SAP, no que no
haya familia. Tratar `relevante=0` como negativo de todas las familias
entrenaba 45 negativos falsos; tratar `relevante=1` de la misma forma (el
hallazgo de la ronda de revisión, 2026-09-27) entrenaba otros 14 -- misma
clase de error, el otro valor de `relevante`.
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
        # legado: relevante=1 significaba «es SAP», no «es TI»; sin tecnología
        # puesta no dice nada de familias -- 14 filas así en producción.
        ("human", 1, None, None, None),
        ("human", 0, "ORACLE", None, "ORACLE"),
    ],
)
def test_etiqueta_humana(source, relevante, tecnologia, secundarias, esperada) -> None:
    assert etiqueta_humana(source, relevante, tecnologia, secundarias) == esperada
