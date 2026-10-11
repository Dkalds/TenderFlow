"""Eval de la ficha del pliego: emparejamiento y métricas.

Hechos mínimos escritos a mano. Lo que se prueba es el código que decide si un
hecho extraído «es» uno del golden —no la calidad de ningún modelo—, porque un
emparejador generoso convierte cualquier extractor en uno bueno.
"""

from __future__ import annotations

from typing import Any

import pytest

from services.rag.fact_sheet import ExtraccionHechos
from services.rag.ficha_eval import (
    agregar,
    cobertura_selector,
    comparar_clave,
    comprobar_minimos,
    emparejar,
    medir_caso,
    minimos_desde,
)
from services.rag.ficha_golden import Caso, CasoGolden, modelo_de
from shared.tender_facts import FactItem, TenderFactSheet

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
        # Una letra de lote no es una palabra vacía.
        ("lots", {"lot_number": "Lote A"}, {"lot_number": "A"}, "igual"),
        ("lots", {"lot_number": "Lote A"}, {"lot_number": "Lote Y"}, "distinta"),
        # Sustituir una palabra no es parafrasear: es otro requisito.
        (
            "certifications",
            {"name": "ENS categoría media"},
            {"name": "ENS categoría alta"},
            "distinta",
        ),
        (
            "certifications",
            {"name": "ISO/IEC 27001:2022"},
            {"name": "ISO/IEC 27017:2022"},
            "distinta",
        ),
        (
            "required_documents",
            {"name": "Declaración responsable de solvencia"},
            {"name": "Declaración responsable del grupo"},
            "distinta",
        ),
        (
            "rate_cards",
            {"role": "Consultor SAP senior", "max_rate_eur_hour": 50},
            {"role": "Consultor SAP junior", "max_rate_eur_hour": 50},
            "distinta",
        ),
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

    # Un duplicado no es un desconocido: casa con algo ya etiquetado. Si saliera
    # como `sin_juzgar` acabaría en los pendientes de revisión, y al marcarlo
    # correcto el golden tendría dos positivos idénticos.
    for completo in (True, False):
        assert _resultados("award_criteria", repetidos, positivos=[golden], completo=completo) == [
            "acierto",
            "duplicado",
        ]


def test_un_error_conocido_repetido_dos_veces_es_error_las_dos() -> None:
    inventado = _hecho("award_criteria", {"weight_pct": 25, "name": "Inventado"})
    repetidos = [
        _hecho("award_criteria", {"weight_pct": 25, "name": "Inventado"}) for _ in range(2)
    ]

    assert _resultados("award_criteria", repetidos, negativos=[inventado], completo=False) == [
        "error_confirmado",
        "error_confirmado",
    ]


def test_el_valor_original_de_un_corregido_en_el_segundo_campo_es_error_confirmado() -> None:
    # La revisión deja corregir los dos campos de la clave. Si el primero
    # (el número de lote) no cambió, el valor malo no puede colarse como acierto.
    bueno = _hecho("lots", {"lot_number": "1", "amount_eur": 120000.0})
    original = _hecho("lots", {"lot_number": "1", "amount_eur": 100000.0})
    repite_el_error = _hecho("lots", {"lot_number": "1", "amount_eur": 100000.0})
    acierta = _hecho("lots", {"lot_number": "1", "amount_eur": 120000.0})

    assert _resultados("lots", [repite_el_error], positivos=[bueno], negativos=[original]) == [
        "error_confirmado"
    ]
    assert _resultados("lots", [acierta], positivos=[bueno], negativos=[original]) == ["acierto"]


def test_un_nombre_corregido_con_el_mismo_peso_tambien_es_error_confirmado() -> None:
    bueno = _hecho("award_criteria", {"weight_pct": 60, "name": "Calidad técnica"})
    original = _hecho("award_criteria", {"weight_pct": 60, "name": "Precio"})
    repite_el_error = _hecho("award_criteria", {"weight_pct": 60, "name": "Precio"})

    assert _resultados(
        "award_criteria", [repite_el_error], positivos=[bueno], negativos=[original]
    ) == ["error_confirmado"]


def test_un_incorrecto_identico_no_acierta_contra_otro_positivo_de_la_pagina() -> None:
    precio = _hecho("award_criteria", {"weight_pct": 40, "name": "Precio"}, cita=_CITA_PRECIO)
    inventado = _hecho("award_criteria", {"weight_pct": 40, "name": "Mejoras"}, cita=_CITA_CALIDAD)
    extraido = _hecho("award_criteria", {"weight_pct": 40, "name": "Mejoras"}, cita=_CITA_CALIDAD)

    emparejamiento = emparejar(
        "award_criteria", [extraido], positivos=[precio], negativos=[inventado], completo=True
    )

    assert [par.resultado for par in emparejamiento.pares] == ["error_confirmado"]
    assert emparejamiento.omitidos == [precio]


def test_sin_dato_que_comparar_la_misma_frase_en_otra_pagina_no_casa() -> None:
    golden = _hecho(
        "guarantees",
        cita="Garantía definitiva: 5 por ciento del presupuesto base de licitación, IVA excluido",
        pagina=10,
    )
    otra = _hecho(
        "guarantees",
        cita="Garantía complementaria de hasta un 5 por ciento del presupuesto base de licitación",
        pagina=44,
    )

    assert _resultados("guarantees", [otra], positivos=[golden]) == ["falso_positivo"]


def test_sin_dato_que_comparar_una_coletilla_comun_en_la_misma_pagina_no_casa() -> None:
    golden = _hecho(
        "technical_solvency",
        cita="Relación de los principales servicios realizados en los últimos tres años, "
        "con importes y fechas",
    )
    otro_requisito = _hecho(
        "technical_solvency",
        cita="Certificados de buena ejecución expedidos en los últimos tres años "
        "por el destinatario",
    )

    assert _resultados("technical_solvency", [otro_requisito], positivos=[golden]) == [
        "falso_positivo"
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


# ── Métricas, mínimos y cobertura del selector ──────────────────────────────


def _caso(
    hechos: list[tuple[str, FactItem]],
    *,
    completo: bool,
    nombre: str = "caso",
    paginas: list[dict[str, Any]] | None = None,
) -> Caso:
    golden = CasoGolden.model_validate(
        {
            "licitacion_id": "EXP-1",
            "completo": completo,
            "capturado_el": "2026-10-11",
            "extraction_version": "tender-facts-v6",
            "model": "modelo-x",
            "status_origen": "extracted",
            "hechos": {
                "award_criteria": [
                    {"veredicto": veredicto, "hecho": hecho.model_dump(mode="json")}
                    for veredicto, hecho in hechos
                ]
            },
        }
    )
    return Caso(nombre=nombre, golden=golden, paginas=paginas or [])


def _extraccion(
    *criterios: FactItem, invalidos: int = 0, inverificables: int = 0
) -> ExtraccionHechos:
    return ExtraccionHechos(
        facts=TenderFactSheet.model_validate(
            {"award_criteria": [c.model_dump(mode="json") for c in criterios]}
        ),
        invalidos=invalidos,
        inverificables=inverificables,
        seleccionadas=[],
    )


def _tres_positivos() -> list[tuple[str, FactItem]]:
    return [
        ("correcto", _hecho("award_criteria", {"weight_pct": 60, "name": "Precio"})),
        (
            "correcto",
            _hecho("award_criteria", {"weight_pct": 30, "name": "Calidad"}, cita=_CITA_CALIDAD),
        ),
        (
            "añadido",
            _hecho("award_criteria", {"weight_pct": 10, "name": "Plazo"}, cita=_CITA_PLAZO),
        ),
    ]


def _cuatro_extraidos() -> list[FactItem]:
    return [
        _hecho("award_criteria", {"weight_pct": 60, "name": "Precio"}),
        _hecho("award_criteria", {"weight_pct": 30, "name": "Calidad"}, cita=_CITA_CALIDAD),
        # Mismo sitio, otro dato.
        _hecho("award_criteria", {"weight_pct": 15, "name": "Plazo"}, cita=_CITA_PLAZO),
        # No casa con nada del golden.
        _hecho(
            "award_criteria",
            {"weight_pct": 5, "name": "Mejoras"},
            cita="Se valorarán las mejoras ofertadas sin coste para la Administración",
            pagina=9,
        ),
    ]


def test_caso_completo_precision_y_cobertura() -> None:
    caso = _caso(_tres_positivos(), completo=True)

    resultado = medir_caso(caso, _extraccion(*_cuatro_extraidos(), invalidos=2, inverificables=1))

    total = resultado.por_familia["award_criteria"]
    assert (total.extraidos, total.positivos, total.aciertos) == (4, 3, 2)
    assert (total.valor_distinto, total.falsos_positivos, total.sin_juzgar) == (1, 1, 0)
    assert (total.precision, total.cobertura) == (0.5, pytest.approx(2 / 3))
    assert (resultado.invalidos, resultado.inverificables, resultado.fallo) == (2, 1, None)
    assert resultado.pendientes == []
    vacia = resultado.por_familia["lots"]
    assert (vacia.precision, vacia.cobertura) == (None, None)


def test_en_un_caso_parcial_lo_no_revisado_no_es_error_y_sale_en_pendientes() -> None:
    caso = _caso(_tres_positivos(), completo=False)
    extraidos = _cuatro_extraidos()

    resultado = medir_caso(caso, _extraccion(*extraidos))

    total = resultado.por_familia["award_criteria"]
    assert (total.aciertos, total.valor_distinto) == (2, 1)
    assert (total.sin_juzgar, total.falsos_positivos) == (1, 0)
    ((familia, pendiente),) = resultado.pendientes
    assert familia == "award_criteria"
    assert pendiente.evidence[0].page_number == 9


def test_un_negativo_del_golden_cuenta_como_error_confirmado() -> None:
    inventado = _hecho("award_criteria", {"weight_pct": 5, "name": "Mejoras"}, cita=_CITA_PLAZO)
    caso = _caso([*_tres_positivos()[:2], ("incorrecto", inventado)], completo=False)

    resultado = medir_caso(caso, _extraccion(inventado))

    total = resultado.por_familia["award_criteria"]
    assert (total.positivos, total.errores_confirmados, total.aciertos) == (2, 1, 0)


def test_una_extraccion_fallida_cuenta_sus_positivos_como_omitidos() -> None:
    caso = _caso(_tres_positivos(), completo=True)

    resultado = medir_caso(caso, None, fallo="respuesta vacía")
    informe = agregar([resultado])

    assert resultado.fallo == "respuesta vacía"
    assert informe.casos_fallidos == 1
    assert informe.totales["cobertura_completos"] == 0.0
    assert informe.totales["precision_completos"] is None


def test_agregar_separa_completos_de_parciales() -> None:
    completo = medir_caso(
        _caso(_tres_positivos(), completo=True, nombre="a"),
        _extraccion(*_cuatro_extraidos(), invalidos=1),
    )
    parcial = medir_caso(
        _caso(_tres_positivos(), completo=False, nombre="b"),
        _extraccion(_cuatro_extraidos()[0], inverificables=2),
    )

    informe = agregar([completo, parcial])

    assert (informe.n_completos, informe.n_parciales, informe.casos_fallidos) == (1, 1, 0)
    assert (informe.invalidos, informe.inverificables) == (1, 2)
    assert informe.completos["award_criteria"].extraidos == 4
    assert informe.parciales["award_criteria"].extraidos == 1
    assert informe.totales == {
        "precision_completos": 0.5,
        "cobertura_completos": pytest.approx(2 / 3),
        "conservados_parciales": pytest.approx(1 / 3),
    }


def test_sin_casos_completos_los_totales_son_none() -> None:
    parcial = medir_caso(_caso(_tres_positivos(), completo=False), _extraccion())

    informe = agregar([parcial])

    assert informe.totales["precision_completos"] is None
    assert informe.totales["cobertura_completos"] is None
    assert informe.totales["conservados_parciales"] == 0.0
    assert agregar([]).totales["conservados_parciales"] is None


def test_comprobar_minimos() -> None:
    assert comprobar_minimos({"precision_completos": 0.8}, {"precision_completos": 0.7}) == []
    assert comprobar_minimos({"precision_completos": 0.7}, {"precision_completos": 0.7}) == []
    (baja,) = comprobar_minimos({"precision_completos": 0.6}, {"precision_completos": 0.7})
    assert "precision_completos" in baja and "0.6" in baja and "0.7" in baja
    (sin_poblacion,) = comprobar_minimos(
        {"precision_completos": None}, {"precision_completos": 0.7}
    )
    assert "sin población" in sin_poblacion
    (ausente,) = comprobar_minimos({}, {"selector_cobertura": 0.9})
    assert "selector_cobertura" in ausente


def test_cobertura_selector_cuenta_el_positivo_si_su_pagina_entro() -> None:
    caso = _caso(
        [
            ("correcto", _hecho("award_criteria", {"weight_pct": 60}, pagina=3)),
            ("correcto", _hecho("award_criteria", {"weight_pct": 40}, pagina=12)),
            ("incorrecto", _hecho("award_criteria", {"weight_pct": 5}, pagina=3)),
        ],
        completo=False,
    )

    assert cobertura_selector(caso, [{"documento_id": 7, "page_number": 3}]) == {
        "award_criteria": (1, 2)
    }
    assert cobertura_selector(caso, [{"documento_id": 8, "page_number": 3}]) == {
        "award_criteria": (0, 2)
    }


def test_minimos_desde_toma_la_peor_ejecucion_menos_dos_puntos() -> None:
    ejecuciones = [
        {"precision_completos": 0.80, "cobertura_completos": 0.61, "conservados_parciales": 0.9},
        {"precision_completos": 0.74, "cobertura_completos": 0.65, "conservados_parciales": 0.9},
        {"precision_completos": 0.79, "cobertura_completos": 0.6049, "conservados_parciales": 0.01},
    ]

    assert minimos_desde(ejecuciones, selector=0.9) == {
        "precision_completos": 0.72,
        "cobertura_completos": 0.584,
        "conservados_parciales": 0.0,
        "selector_cobertura": 0.9,
    }


def test_minimos_desde_no_inventa_un_minimo_sin_poblacion() -> None:
    sin_completos = {
        "precision_completos": None,
        "cobertura_completos": None,
        "conservados_parciales": 0.9,
    }

    with pytest.raises(ValueError, match="precision_completos"):
        minimos_desde([sin_completos], selector=0.9)


def test_un_duplicado_cuenta_contra_la_precision_y_no_va_a_pendientes() -> None:
    caso = _caso(_tres_positivos()[:1], completo=False)
    precio = _cuatro_extraidos()[0]

    resultado = medir_caso(caso, _extraccion(precio, precio))

    total = resultado.por_familia["award_criteria"]
    assert (total.aciertos, total.duplicados, total.sin_juzgar) == (1, 1, 0)
    assert total.precision == 0.5
    assert resultado.pendientes == []
    assert (total + total).duplicados == 2


def test_una_extraccion_sin_hechos_se_cuenta_como_vacia_y_no_como_fallida() -> None:
    vacia = medir_caso(_caso(_tres_positivos(), completo=True, nombre="a"), _extraccion())
    fallida = medir_caso(_caso(_tres_positivos(), completo=True, nombre="b"), None, fallo="caído")
    normal = medir_caso(
        _caso(_tres_positivos(), completo=True, nombre="c"), _extraccion(*_cuatro_extraidos())
    )

    informe = agregar([vacia, fallida, normal])

    assert (informe.extracciones_vacias, informe.casos_fallidos) == (1, 1)
