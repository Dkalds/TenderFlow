"""Denominador declarado del embudo del Resumen (`construir_embudo`).

Ítem P3 «El embudo del Resumen mide sus porcentajes contra todo el corpus»:
con `AGR` en el ~93 % del corpus, dividir los cinco escalones entre el total
los dejaba sumando ~6,7 %. Desde 2026-09-18 los escalones se dividen entre su
propia suma y la respuesta declara el denominador y lo que queda fuera.

Función pura sobre el diccionario de `overview_funnel`: no toca BD.
"""

from __future__ import annotations

import pytest

from services.analytics.overview import (
    ESCALONES_EMBUDO,
    FUERA_DEL_EMBUDO,
    FunnelStep,
    OverviewResult,
    construir_embudo,
)

#: La forma del corpus real: un embudo pequeño y un `AGR` enorme.
_CONTEOS = {
    "PUB": 30,
    "EV": 20,
    "RES": 10,
    "ADJ": 35,
    "ANUL": 5,
    "PRE": 2,
    "AGR": 1380,
    "EJEC": 3,
    "CPM": 0,
    "total": 1485,
}


def _por_estado(pasos: list[FunnelStep]) -> dict[str, FunnelStep]:
    return {p.estado: p for p in pasos}


def test_los_cinco_escalones_suman_cien():
    pasos, denominador, _ = construir_embudo(_CONTEOS)
    en_embudo = [p for p in pasos if p.en_embudo]
    assert [p.estado for p in en_embudo] == list(ESCALONES_EMBUDO)
    assert denominador == 100
    assert sum(p.pct for p in en_embudo) == pytest.approx(100.0)
    assert _por_estado(pasos)["ADJ"].pct == pytest.approx(35.0)


def test_lo_que_no_es_escalon_se_declara_fuera_y_contra_el_total():
    pasos, denominador, fuera = construir_embudo(_CONTEOS)
    agr = _por_estado(pasos)["AGR"]
    assert agr.en_embudo is False
    assert agr.pct == pytest.approx(1380 / 1485 * 100)
    assert fuera == 1485 - 100
    assert denominador + fuera == _CONTEOS["total"]
    assert [p.estado for p in pasos if not p.en_embudo] == list(FUERA_DEL_EMBUDO)


def test_ninguna_fila_desaparece():
    """OTROS recoge lo que no cae en ningún código y los tramos suman el total."""
    conteos = {**_CONTEOS, "total": 1490}
    pasos, _, fuera = construir_embudo(conteos)
    otros = _por_estado(pasos)["OTROS"]
    assert otros.n == 5
    assert otros.en_embudo is False
    assert sum(p.n for p in pasos) == 1490
    assert fuera == 1490 - 100


def test_sin_otros_cuando_el_corpus_esta_limpio():
    pasos, _, _ = construir_embudo(_CONTEOS)
    assert "OTROS" not in _por_estado(pasos)


def test_ambito_vacio_no_divide_por_cero():
    pasos, denominador, fuera = construir_embudo({"total": 0})
    assert (denominador, fuera) == (0, 0)
    assert all(p.pct == 0.0 and p.n == 0 for p in pasos)


def test_ambito_sin_escalones_no_inventa_porcentajes():
    """Un ámbito todo `AGR` (p.ej. filtrado a Cataluña) deja el embudo a cero."""
    pasos, denominador, fuera = construir_embudo({"AGR": 50, "total": 50})
    assert denominador == 0
    assert fuera == 50
    assert all(p.pct == 0.0 for p in pasos if p.en_embudo)
    assert _por_estado(pasos)["AGR"].pct == pytest.approx(100.0)


def test_el_contrato_documenta_el_denominador():
    """AGENTS §3.5: el cambio de semántica de `pct` queda escrito en el DTO."""
    assert "funnel_denominador" in (FunnelStep.model_fields["pct"].description or "")
    assert FunnelStep.model_fields["en_embudo"].default is True
    vacio = OverviewResult()
    assert (vacio.funnel_denominador, vacio.fuera_del_embudo) == (0, 0)
