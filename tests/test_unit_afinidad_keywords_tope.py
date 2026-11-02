"""Tope de las keywords de afinidad (auditoría 2026-11, ruta 19, G1-5-1).

``_keyword_pattern`` compila una sola alternancia con todas las keywords y la
evalúa sobre las ~1.600 candidatas del Radar en cada carga. Sin tope, un cuerpo
de 1 MB con decenas de miles de keywords bloqueaba el GIL de todo el proceso.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from api.routes.me import UserProfileBody
from services.analytics.affinity import (
    MAX_KEYWORDS_AFINIDAD,
    MAX_LONGITUD_KEYWORD,
    build_portfolio,
)


def test_el_perfil_acepta_hasta_el_tope() -> None:
    cuerpo = UserProfileBody(afinidad_keywords=[f"kw{i}" for i in range(MAX_KEYWORDS_AFINIDAD)])

    assert cuerpo.afinidad_keywords is not None
    assert len(cuerpo.afinidad_keywords) == MAX_KEYWORDS_AFINIDAD


def test_el_perfil_rechaza_una_lista_mas_larga_que_el_tope() -> None:
    with pytest.raises(ValidationError, match="Máximo 50 keywords"):
        UserProfileBody(afinidad_keywords=["sap"] * (MAX_KEYWORDS_AFINIDAD + 1))


def test_el_perfil_rechaza_la_lista_que_cabe_en_un_megabyte() -> None:
    """El caso del informe: ~170.000 keywords de tres letras."""
    with pytest.raises(ValidationError):
        UserProfileBody(afinidad_keywords=["abc"] * 170_000)


def test_el_perfil_rechaza_una_keyword_demasiado_larga() -> None:
    with pytest.raises(ValidationError, match="60 caracteres"):
        UserProfileBody(afinidad_keywords=["x" * (MAX_LONGITUD_KEYWORD + 1)])


def test_el_perfil_sin_keywords_o_con_lista_vacia_sigue_valiendo() -> None:
    assert UserProfileBody().afinidad_keywords is None
    assert UserProfileBody(afinidad_keywords=[]).afinidad_keywords == []


def test_el_portfolio_acota_lo_que_ya_estaba_guardado() -> None:
    """Un perfil guardado antes del tope no pasó por el validador del cuerpo."""
    portfolio = build_portfolio(keywords=[f"kw{i}" for i in range(5_000)])

    assert len(portfolio.keywords) == MAX_KEYWORDS_AFINIDAD
    assert portfolio.keywords[0] == "kw0"


def test_las_keywords_largas_se_descartan_antes_de_contar() -> None:
    largas = ["x" * (MAX_LONGITUD_KEYWORD + 1)] * 10
    validas = [f"kw{i}" for i in range(MAX_KEYWORDS_AFINIDAD)]

    portfolio = build_portfolio(keywords=[*largas, *validas])

    assert portfolio.keywords == tuple(validas)
