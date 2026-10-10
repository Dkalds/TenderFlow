"""Eval de la ficha del pliego: emparejamiento y métricas.

Hechos mínimos escritos a mano. Lo que se prueba es el código que decide si un
hecho extraído «es» uno del golden —no la calidad de ningún modelo—, porque un
emparejador generoso convierte cualquier extractor en uno bueno.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.rag.ficha_eval import comparar_clave, emparejar
from services.rag.ficha_golden import modelo_de
from shared.tender_facts import FactItem

_CITA_PRECIO = "El criterio precio tendrá una ponderación del 60 por ciento del total"
_CITA_CALIDAD = "La calidad técnica de la oferta se valorará con hasta cuarenta puntos"
_CITA_PLAZO = "La reducción del plazo de ejecución se puntuará de forma proporcional"

#: Campos obligatorios de algunas familias, para poder escribir hechos mínimos.
_RELLENO: dict[str, dict[str, Any]] = {
    "award_criteria": {"name": "Criterio"},
    "certifications": {"name": "Certificación"},
    "service_levels": {"name": "Indicador"},
    "critical_deadlines": {"name": "Hito"},
    "technologies": {"name": "Tecnología"},
    "required_documents": {"name": "Documento"},
    "rate_cards": {"role": "Perfil"},
    "budget_breakdown": {"concept": "Partida"},
}


def _hecho(
    familia: str,
    campos: dict[str, Any] | None = None,
    *,
    cita: str = _CITA_PRECIO,
    pagina: int = 3,
    documento: int = 7,
) -> FactItem:
    return modelo_de(familia).model_validate(
        {
            "description": "Hecho de prueba",
            "confidence": 0.9,
            "evidence": [{"documento_id": documento, "page_number": pagina, "quote": cita}],
            **_RELLENO.get(familia, {}),
            **(campos or {}),
        }
    )


@pytest.mark.parametrize(
    ("familia", "a", "b", "esperado"),
    [
        ("award_criteria", {"weight_pct": 60}, {"weight_pct": 60.2}, "igual"),
        ("award_criteria", {"weight_pct": 60}, {"weight_pct": 61}, "distinta"),
        # El peso decide aunque los nombres no se parezcan.
        (
            "award_criteria",
            {"weight_pct": 60, "name": "A"},
            {"weight_pct": 60, "name": "B"},
            "igual",
        ),
        ("award_criteria", {"name": "Precio"}, {"name": "Oferta económica (precio)"}, "igual"),
        ("award_criteria", {"name": "Precio"}, {"name": "Memoria técnica"}, "distinta"),
        ("certifications", {"name": "ISO 27001"}, {"name": "ISO/IEC 27001:2022"}, "igual"),
        ("certifications", {"name": "ISO 9001"}, {"name": "ISO 27001"}, "distinta"),
        ("lots", {"lot_number": "Lote 1"}, {"lot_number": "1"}, "igual"),
        ("lots", {"lot_number": "1"}, {"lot_number": "2"}, "distinta"),
        ("lots", {"amount_eur": 1000.0}, {"lot_number": "1", "amount_eur": 1000.0}, "igual"),
        (
            "price_formula",
            {"formula_type": "otra"},
            {"formula_type": "proporcional_inversa"},
            "distinta",
        ),
        (
            "price_formula",
            {"formula_type": "proporcional_inversa", "max_points": 60},
            {"formula_type": "proporcional_inversa"},
            "igual",
        ),
        (
            "price_formula",
            {"formula_type": "proporcional_inversa", "max_points": 60},
            {"formula_type": "proporcional_inversa", "max_points": 40},
            "distinta",
        ),
        ("economic_solvency", {"amount_eur": None}, {"amount_eur": 5000.0}, "sin_comparar"),
        ("economic_solvency", {"amount_eur": 5000.0}, {"amount_eur": 5010.0}, "igual"),
        ("economic_solvency", {"amount_eur": 5000.0}, {"amount_eur": 50000.0}, "distinta"),
        ("technical_solvency", {}, {}, "sin_comparar"),
        (
            "team_requirements",
            {"role": "Jefe de proyecto", "minimum_years": 5},
            {"role": "Jefe de proyecto SAP", "minimum_years": 5},
            "igual",
        ),
        (
            "team_requirements",
            {"role": "Jefe de proyecto", "minimum_years": 5},
            {"role": "Jefe de proyecto", "minimum_years": 10},
            "distinta",
        ),
        ("team_requirements", {"minimum_years": 5}, {"minimum_years": 5}, "sin_comparar"),
        (
            "critical_deadlines",
            {"date_value": "2026-11-30", "name": "Fin de plazo"},
            {"date_value": "2026-11-30", "name": "Presentación de ofertas"},
            "igual",
        ),
        (
            "critical_deadlines",
            {"date_value": "2026-11-30"},
            {"date_value": "2026-12-01"},
            "distinta",
        ),
        (
            "rate_cards",
            {"role": "Consultor", "max_rate_eur_hour": 50},
            {"role": "Consultor", "max_rate_eur_hour": 50.1},
            "igual",
        ),
        ("budget_breakdown", {"amount_eur": 100.0}, {"amount_eur": 200.0}, "distinta"),
    ],
)
def test_comparar_clave(familia: str, a: dict[str, Any], b: dict[str, Any], esperado: str) -> None:
    assert comparar_clave(familia, _hecho(familia, a), _hecho(familia, b)) == esperado
    assert comparar_clave(familia, _hecho(familia, b), _hecho(familia, a)) == esperado


def _resultados(familia: str, extraidos: list[FactItem], **kwargs: Any) -> list[str]:
    kwargs.setdefault("positivos", [])
    kwargs.setdefault("negativos", [])
    kwargs.setdefault("completo", True)
    return [par.resultado for par in emparejar(familia, extraidos, **kwargs).pares]


def test_misma_clave_en_pagina_contigua_es_acierto_sin_solape_de_cita() -> None:
    golden = _hecho("award_criteria", {"weight_pct": 60}, cita=_CITA_PRECIO, pagina=3)
    contigua = _hecho("award_criteria", {"weight_pct": 60}, cita=_CITA_CALIDAD, pagina=4)
    lejana = _hecho("award_criteria", {"weight_pct": 60}, cita=_CITA_CALIDAD, pagina=5)
    otro_documento = _hecho(
        "award_criteria", {"weight_pct": 60}, cita=_CITA_CALIDAD, pagina=3, documento=8
    )

    assert _resultados("award_criteria", [contigua], positivos=[golden]) == ["acierto"]
    assert _resultados("award_criteria", [lejana], positivos=[golden]) == ["falso_positivo"]
    assert _resultados("award_criteria", [otro_documento], positivos=[golden]) == ["falso_positivo"]


def test_cita_solapada_con_otro_peso_es_valor_distinto_y_el_positivo_queda_omitido() -> None:
    golden = _hecho("award_criteria", {"weight_pct": 60})
    extraido = _hecho("award_criteria", {"weight_pct": 40})

    emparejamiento = emparejar(
        "award_criteria", [extraido], positivos=[golden], negativos=[], completo=True
    )

    (par,) = emparejamiento.pares
    assert par.resultado == "valor_distinto"
    assert par.golden is golden
    assert emparejamiento.omitidos == [golden]


def test_dos_criterios_del_mismo_peso_en_la_misma_pagina_casan_cada_uno_con_el_suyo() -> None:
    calidad = _hecho("award_criteria", {"weight_pct": 10, "name": "Calidad"}, cita=_CITA_CALIDAD)
    plazo = _hecho("award_criteria", {"weight_pct": 10, "name": "Plazo"}, cita=_CITA_PLAZO)
    extraido_plazo = _hecho("award_criteria", {"weight_pct": 10, "name": "Plazo"}, cita=_CITA_PLAZO)
    extraido_calidad = _hecho(
        "award_criteria", {"weight_pct": 10, "name": "Calidad"}, cita=_CITA_CALIDAD
    )

    emparejamiento = emparejar(
        "award_criteria",
        [extraido_plazo, extraido_calidad],
        positivos=[calidad, plazo],
        negativos=[],
        completo=True,
    )

    assert [par.resultado for par in emparejamiento.pares] == ["acierto", "acierto"]
    assert emparejamiento.pares[0].golden is plazo
    assert emparejamiento.pares[1].golden is calidad
    assert emparejamiento.omitidos == []


def test_un_hecho_repetido_solo_acierta_una_vez() -> None:
    golden = _hecho("award_criteria", {"weight_pct": 60})
    repetidos = [_hecho("award_criteria", {"weight_pct": 60}) for _ in range(2)]

    assert _resultados("award_criteria", repetidos, positivos=[golden], completo=True) == [
        "acierto",
        "falso_positivo",
    ]
    assert _resultados("award_criteria", repetidos, positivos=[golden], completo=False) == [
        "acierto",
        "sin_juzgar",
    ]


def test_un_negativo_conocido_es_error_confirmado() -> None:
    inventado = _hecho("award_criteria", {"weight_pct": 25, "name": "Inventado"})
    extraido = _hecho("award_criteria", {"weight_pct": 25, "name": "Inventado"})

    emparejamiento = emparejar(
        "award_criteria", [extraido], positivos=[], negativos=[inventado], completo=False
    )

    (par,) = emparejamiento.pares
    assert (par.resultado, par.golden) == ("error_confirmado", inventado)


def test_repetir_el_valor_original_de_un_corregido_es_error_confirmado_no_valor_distinto() -> None:
    bueno = _hecho("award_criteria", {"weight_pct": 60})
    original = _hecho("award_criteria", {"weight_pct": 40})
    extraido = _hecho("award_criteria", {"weight_pct": 40})
    otro_error = _hecho("award_criteria", {"weight_pct": 55})

    assert _resultados("award_criteria", [extraido], positivos=[bueno], negativos=[original]) == [
        "error_confirmado"
    ]
    # Un valor malo que nadie había visto: mismo sitio, otro dato.
    assert _resultados("award_criteria", [otro_error], positivos=[bueno], negativos=[original]) == [
        "valor_distinto"
    ]


def test_familia_sin_clave_no_casa_solo_por_la_pagina() -> None:
    golden = _hecho("technical_solvency", cita=_CITA_PRECIO)
    misma_pagina = _hecho("technical_solvency", cita=_CITA_CALIDAD)
    misma_cita = _hecho("technical_solvency", cita=_CITA_PRECIO)

    assert _resultados("technical_solvency", [misma_pagina], positivos=[golden]) == [
        "falso_positivo"
    ]
    assert _resultados("technical_solvency", [misma_cita], positivos=[golden]) == ["acierto"]


def test_importe_ausente_no_casa_solo_por_la_pagina() -> None:
    golden = _hecho("economic_solvency", {"amount_eur": 5000.0}, cita=_CITA_PRECIO)
    sin_importe = _hecho("economic_solvency", {"amount_eur": None}, cita=_CITA_CALIDAD)
    sin_importe_misma_cita = _hecho("economic_solvency", {"amount_eur": None}, cita=_CITA_PRECIO)

    assert _resultados("economic_solvency", [sin_importe], positivos=[golden]) == ["falso_positivo"]
    # Con la misma cita sí: no hay dato que contradiga al del golden.
    assert _resultados("economic_solvency", [sin_importe_misma_cita], positivos=[golden]) == [
        "acierto"
    ]


def test_una_cita_abreviada_con_elipsis_casa_con_la_completa() -> None:
    golden = _hecho("technical_solvency", cita=_CITA_PRECIO)
    abreviada = _hecho(
        "technical_solvency", cita="El criterio precio tendrá una ponderación... del total"
    )

    assert _resultados("technical_solvency", [abreviada], positivos=[golden]) == ["acierto"]


def test_una_coincidencia_corta_entre_citas_no_es_ancla() -> None:
    golden = _hecho("technical_solvency", cita="Se exige solvencia técnica acreditada")
    otra = _hecho(
        "technical_solvency", cita="Se exige una garantía definitiva del cinco por ciento"
    )

    assert _resultados("technical_solvency", [otra], positivos=[golden]) == ["falso_positivo"]


def test_sin_hechos_extraidos_todos_los_positivos_quedan_omitidos() -> None:
    golden = [_hecho("award_criteria", {"weight_pct": 60})]

    emparejamiento = emparejar("award_criteria", [], positivos=golden, negativos=[], completo=True)

    assert emparejamiento.pares == []
    assert emparejamiento.omitidos == golden
