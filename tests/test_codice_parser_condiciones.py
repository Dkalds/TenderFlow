"""Criterios, garantías y solvencia tipados desde CODICE (v149).

Hasta v149 el parser leía de ``cac:TenderingTerms`` un único agregado,
``peso_precio_pct``, y tiraba el resto: qué criterios, con qué peso, qué
garantía y qué solvencia. Ese dato solo llegaba por la ficha LLM del pliego,
que no corre en lote. Estos tests congelan la lectura tipada del bloque, a
nivel de expediente y de lote.

Lo que se fija, por orden:

- Los criterios conservan el **peso publicado** y, aparte, un ``peso_pct``
  que solo se rellena cuando la escala es deducible con la misma regla que
  ``parse_peso_precio`` (suma ~100 o ~1). Un subcriterio reparte el peso de su
  padre, no el del expediente: su ``peso_pct`` queda ``None``.
- Los códigos de tipo viajan **crudos**: las listas de CODICE no están
  verificadas en el repo y traducirlas aquí congelaría una copia inventada.
- Un bloque sin ningún dato útil se descarta; uno ausente da listas vacías,
  que el upsert interpreta como «no lo trae», nunca como «bórralo».
- Las dos grafías del esquema (CODICE ``...Criteria``, UBL 2.1
  ``...Criterion``) se leen igual.
"""

from __future__ import annotations

import textwrap

import pytest
from lxml import etree

from scraper.codice_parser import parse_condiciones, parse_entry, parse_entry_unfiltered

_NS = {
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


def _entry(*, terminos: str = "", lotes: str = "", lic_id: str = "COND-001") -> etree._Element:
    """Entry CODICE mínima del universo SAP con los bloques que se pasen."""
    xml = textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{_NS["cbc"]}"
               xmlns:cac="{_NS["cac"]}"
               xmlns:cacext="{_NS["cacext"]}"
               xmlns:cbcext="{_NS["cbcext"]}">
          <id>https://example.com/{lic_id}</id>
          <title>Soporte SAP S/4HANA</title>
          <updated>2026-10-01T10:00:00Z</updated>
          <link href="https://example.com/{lic_id}" rel="alternate"/>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>{lic_id}</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
            <cac:ProcurementProject>
              <cbc:Name>Soporte SAP S/4HANA</cbc:Name>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">500000.00</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
            </cac:ProcurementProject>
            {terminos}
            {lotes}
          </cacext:ContractFolderStatus>
        </entry>
    """)
    return etree.fromstring(xml.encode())


def _terminos(*bloques: str) -> str:
    return f"<cac:TenderingTerms>{''.join(bloques)}</cac:TenderingTerms>"


def _criterios(*criterios: str) -> str:
    return f"<cac:AwardingTerms>{''.join(criterios)}</cac:AwardingTerms>"


def _criterio(
    descripcion: str,
    peso: str | None,
    *,
    tipo: str | None = None,
    subtipo: str | None = None,
    nota: str | None = None,
    hijos: str = "",
    tag: str = "AwardingCriteria",
) -> str:
    sufijo = "Criteria" if tag.endswith("Criteria") else "Criterion"
    partes = [
        f"<cbc:Awarding{sufijo}TypeCode>{tipo}</cbc:Awarding{sufijo}TypeCode>" if tipo else "",
        f"<cbc:Awarding{sufijo}SubTypeCode>{subtipo}</cbc:Awarding{sufijo}SubTypeCode>"
        if subtipo
        else "",
        f"<cbc:Description>{descripcion}</cbc:Description>",
        f"<cbc:WeightNumeric>{peso}</cbc:WeightNumeric>" if peso is not None else "",
        f"<cbc:Note>{nota}</cbc:Note>" if nota else "",
        hijos,
    ]
    return f"<cac:{tag}>{''.join(partes)}</cac:{tag}>"


def _lote(numero: str | None, terminos: str) -> str:
    id_xml = f"<cbc:ID>{numero}</cbc:ID>" if numero is not None else ""
    return (
        f"<cac:ProcurementProjectLot>{id_xml}"
        "<cac:ProcurementProject><cbc:Name>Lote</cbc:Name></cac:ProcurementProject>"
        f"{terminos}</cac:ProcurementProjectLot>"
    )


# ─── Criterios de adjudicación ───────────────────────────────────────────────


def test_criterios_del_expediente_con_peso_tipo_y_nota() -> None:
    entry = _entry(
        terminos=_terminos(
            _criterios(
                _criterio("Oferta económica", "60", tipo="1", subtipo="3", nota="Fórmula lineal"),
                _criterio("Memoria técnica", "40", tipo="2"),
            )
        )
    )

    criterios = parse_condiciones(entry).criterios

    assert [(c.orden, c.descripcion, c.peso, c.peso_pct) for c in criterios] == [
        (1, "Oferta económica", 60.0, 60.0),
        (2, "Memoria técnica", 40.0, 40.0),
    ]
    precio, memoria = criterios
    assert precio.es_precio is True
    assert memoria.es_precio is False
    assert (precio.tipo_codigo, precio.subtipo_codigo, precio.nota) == ("1", "3", "Fórmula lineal")
    assert all(c.lote_numero is None and c.padre_orden is None for c in criterios)


def test_escala_en_fracciones_se_normaliza_a_porcentaje() -> None:
    entry = _entry(
        terminos=_terminos(_criterios(_criterio("Precio", "0.7"), _criterio("Calidad", "0.3")))
    )

    criterios = parse_condiciones(entry).criterios

    assert [c.peso for c in criterios] == [0.7, 0.3]
    assert [c.peso_pct for c in criterios] == pytest.approx([70.0, 30.0])


def test_escala_indeducible_conserva_el_peso_pero_no_inventa_porcentaje() -> None:
    """Solo se publica un criterio de 60: el denominador no está en el feed."""
    entry = _entry(terminos=_terminos(_criterios(_criterio("Precio", "60"))))

    (criterio,) = parse_condiciones(entry).criterios

    assert criterio.peso == 60.0
    assert criterio.peso_pct is None


def test_subcriterios_apuntan_a_su_padre_y_no_tienen_porcentaje() -> None:
    hijos = _criterio("Precio hora senior", "60", tag="SubordinateAwardingCriteria") + _criterio(
        "Precio hora junior", "40", tag="SubordinateAwardingCriteria"
    )
    entry = _entry(
        terminos=_terminos(
            _criterios(_criterio("Oferta económica", "55", hijos=hijos), _criterio("Memoria", "45"))
        )
    )

    criterios = parse_condiciones(entry).criterios

    assert [(c.orden, c.padre_orden, c.descripcion) for c in criterios] == [
        (1, None, "Oferta económica"),
        (2, 1, "Precio hora senior"),
        (3, 1, "Precio hora junior"),
        (4, None, "Memoria"),
    ]
    # La escala se deduce de los criterios raíz (55 + 45), no de los hijos.
    assert criterios[0].peso_pct == 55.0
    assert criterios[3].peso_pct == 45.0
    assert criterios[1].peso_pct is None and criterios[2].peso_pct is None


def test_grafia_ubl_21_se_lee_igual() -> None:
    entry = _entry(
        terminos=_terminos(
            _criterios(
                _criterio("Precio", "80", tipo="PRICE", tag="AwardingCriterion"),
                _criterio("Calidad", "20", tipo="QUALITY", tag="AwardingCriterion"),
            )
        )
    )

    criterios = parse_condiciones(entry).criterios

    assert [(c.descripcion, c.tipo_codigo, c.peso_pct) for c in criterios] == [
        ("Precio", "PRICE", 80.0),
        ("Calidad", "QUALITY", 20.0),
    ]
    assert criterios[0].es_precio is True


def test_criterio_sin_descripcion_ni_peso_se_descarta() -> None:
    entry = _entry(
        terminos=_terminos(
            _criterios("<cac:AwardingCriteria/>", _criterio("Precio", "100")),
        )
    )

    criterios = parse_condiciones(entry).criterios

    assert [(c.orden, c.descripcion) for c in criterios] == [(1, "Precio")]


# ─── Por lote ────────────────────────────────────────────────────────────────


def test_criterios_por_lote_llevan_su_numero_y_su_propia_escala() -> None:
    entry = _entry(
        terminos=_terminos(_criterios(_criterio("Precio", "100"))),
        lotes=_lote(
            "1", _terminos(_criterios(_criterio("Precio", "0.5"), _criterio("Plan", "0.5")))
        )
        + _lote("2", _terminos(_criterios(_criterio("Precio", "70"))))
        + _lote(None, _terminos(_criterios(_criterio("Huérfano", "100")))),
    )

    criterios = parse_condiciones(entry).criterios

    assert [(c.lote_numero, c.orden, c.descripcion, c.peso_pct) for c in criterios] == [
        (None, 1, "Precio", 100.0),
        ("1", 1, "Precio", 50.0),
        ("1", 2, "Plan", 50.0),
        # El lote 2 publica solo 70: escala indeducible dentro de SU ámbito.
        ("2", 1, "Precio", None),
    ]


# ─── Garantías ───────────────────────────────────────────────────────────────


def test_garantias_con_tipo_porcentaje_e_importe() -> None:
    entry = _entry(
        terminos=_terminos(
            "<cac:RequiredFinancialGuarantee>"
            "<cbc:GuaranteeTypeCode>2</cbc:GuaranteeTypeCode>"
            "<cbc:AmountRate>5</cbc:AmountRate>"
            "</cac:RequiredFinancialGuarantee>"
            "<cac:RequiredFinancialGuarantee>"
            "<cbc:GuaranteeTypeCode>1</cbc:GuaranteeTypeCode>"
            '<cbc:LiabilityAmount currencyID="EUR">3000.50</cbc:LiabilityAmount>'
            "<cbc:Description>Provisional por lote</cbc:Description>"
            "</cac:RequiredFinancialGuarantee>"
            "<cac:RequiredFinancialGuarantee/>"
        ),
        lotes=_lote(
            "3",
            _terminos(
                "<cac:RequiredFinancialGuarantee><cbc:AmountRate>3</cbc:AmountRate>"
                "</cac:RequiredFinancialGuarantee>"
            ),
        ),
    )

    garantias = parse_condiciones(entry).garantias

    assert [
        (g.lote_numero, g.orden, g.tipo_codigo, g.porcentaje, g.importe, g.moneda, g.descripcion)
        for g in garantias
    ] == [
        (None, 1, "2", 5.0, None, None, None),
        (None, 2, "1", None, 3000.5, "EUR", "Provisional por lote"),
        ("3", 1, None, 3.0, None, None, None),
    ]


# ─── Solvencia ───────────────────────────────────────────────────────────────


def test_solvencia_tecnica_economica_y_clasificacion() -> None:
    entry = _entry(
        terminos=_terminos(
            "<cac:TendererQualificationRequest>"
            "<cac:TechnicalEvaluationCriteria>"
            "<cbc:EvaluationCriteriaTypeCode>2</cbc:EvaluationCriteriaTypeCode>"
            "<cbc:Description>Tres servicios similares en los últimos tres años</cbc:Description>"
            "</cac:TechnicalEvaluationCriteria>"
            "<cac:FinancialEvaluationCriteria>"
            "<cbc:EvaluationCriteriaTypeCode>1</cbc:EvaluationCriteriaTypeCode>"
            "<cbc:Description>Volumen anual de negocios</cbc:Description>"
            '<cbc:ThresholdAmount currencyID="EUR">750000</cbc:ThresholdAmount>'
            "</cac:FinancialEvaluationCriteria>"
            "<cac:RequiredBusinessClassificationScheme>"
            "<cac:ClassificationCategory><cbc:CodeValue>V2</cbc:CodeValue>"
            "<cbc:Name>Servicios de telecomunicaciones</cbc:Name></cac:ClassificationCategory>"
            "</cac:RequiredBusinessClassificationScheme>"
            "</cac:TendererQualificationRequest>"
        )
    )

    solvencia = parse_condiciones(entry).solvencia

    assert [
        (s.orden, s.clase, s.tipo_codigo, s.descripcion, s.umbral_importe, s.moneda)
        for s in solvencia
    ] == [
        (1, "tecnica", "2", "Tres servicios similares en los últimos tres años", None, None),
        (2, "economica", "1", "Volumen anual de negocios", 750000.0, "EUR"),
        (3, "clasificacion", "V2", "Servicios de telecomunicaciones", None, None),
    ]


def test_solvencia_grafia_criterion_y_por_lote() -> None:
    entry = _entry(
        lotes=_lote(
            "1",
            _terminos(
                "<cac:TendererQualificationRequest>"
                "<cac:FinancialEvaluationCriterion>"
                "<cbc:EvaluationCriterionTypeCode>3</cbc:EvaluationCriterionTypeCode>"
                "<cbc:Description>Seguro de responsabilidad civil</cbc:Description>"
                "</cac:FinancialEvaluationCriterion>"
                "<cac:TechnicalEvaluationCriteria/>"
                "</cac:TendererQualificationRequest>"
            ),
        )
    )

    (requisito,) = parse_condiciones(entry).solvencia

    assert (requisito.lote_numero, requisito.clase, requisito.tipo_codigo) == (
        "1",
        "economica",
        "3",
    )


# ─── Ausencia y camino de producción ─────────────────────────────────────────


def test_sin_tendering_terms_las_listas_quedan_vacias() -> None:
    condiciones = parse_condiciones(_entry())

    assert condiciones.criterios == []
    assert condiciones.garantias == []
    assert condiciones.solvencia == []


@pytest.mark.parametrize("parse", [parse_entry, parse_entry_unfiltered])
def test_parse_entry_lleva_las_condiciones_en_la_licitacion(parse) -> None:  # type: ignore[no-untyped-def]
    entry = _entry(
        terminos=_terminos(
            _criterios(_criterio("Precio", "60"), _criterio("Calidad", "40")),
            "<cac:RequiredFinancialGuarantee><cbc:AmountRate>5</cbc:AmountRate>"
            "</cac:RequiredFinancialGuarantee>",
        )
    )

    lic = parse(entry)

    assert lic is not None
    assert lic.condiciones is not None
    assert [c.descripcion for c in lic.condiciones.criterios] == ["Precio", "Calidad"]
    assert [g.porcentaje for g in lic.condiciones.garantias] == [5.0]
    # El agregado de v85 sigue saliendo del mismo bloque, y coincide.
    assert lic.peso_precio_pct == 60.0
