"""Lectura de la prórroga prevista desde la ficha del pliego (funciones puras)."""

from __future__ import annotations

import json

import pytest

from services.renovaciones_prorroga import (
    meses_de_prorroga,
    meses_de_prorroga_en_texto,
    sumar_meses,
)


@pytest.mark.parametrize(
    ("texto", "meses"),
    [
        ("Prórroga de 12 meses", 12),
        ("prorrogable por 2 años", 24),
        ("Podrá prorrogarse hasta un máximo de 24 meses adicionales", 24),
        ("Dos prórrogas anuales", 24),
        ("prórroga de un año", 12),
        ("Prórroga de 6 (seis) meses", 6),
        ("Prórroga de 12 meses, hasta un máximo de 36 meses en total", 36),
        ("No se contempla prórroga", None),
        ("", None),
        ("Prórroga de 500 años", None),
    ],
)
def test_lee_la_duracion_declarada(texto: str, meses: int | None) -> None:
    assert meses_de_prorroga_en_texto(texto) == meses


def test_meses_de_prorroga_lee_extensions_de_la_ficha() -> None:
    ficha = {
        "extensions": [
            {"description": "Prórroga de 12 meses", "confidence": 0.9},
            {"description": "Segunda prórroga de otros 12 meses", "confidence": 0.7},
        ]
    }
    assert meses_de_prorroga(ficha) == 12
    assert meses_de_prorroga(json.dumps(ficha)) == 12


def test_meses_de_prorroga_tolera_fichas_sin_clausula_o_corruptas() -> None:
    assert meses_de_prorroga(None) is None
    assert meses_de_prorroga({}) is None
    assert meses_de_prorroga({"extensions": []}) is None
    assert meses_de_prorroga("{no es json") is None
    assert meses_de_prorroga("[]") is None
    assert meses_de_prorroga({"extensions": [{"description": None}, "texto suelto"]}) is None


def test_sumar_meses_recorta_al_ultimo_dia_del_mes() -> None:
    assert sumar_meses("2026-01-31", 1) == "2026-02-28"
    assert sumar_meses("2026-11-30", 3) == "2027-02-28"
    assert sumar_meses("2026-06-15T00:00:00", 12) == "2027-06-15"
    assert sumar_meses(None, 12) is None
    assert sumar_meses("2026-06-15", None) is None
    assert sumar_meses("no-fecha", 1) is None
