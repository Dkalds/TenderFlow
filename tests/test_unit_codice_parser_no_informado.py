"""Lo que CODICE publica sin informar no se guarda como si fuera un dato.

Tres fallos del parser que el ítem de las condiciones oficiales dejó anotados
el 2026-10-24 y se arreglaron el 2026-10-25:

- ``fecha_publicacion`` acababa con el ``updated`` entero (timestamp con hora y
  offset) cuando el expediente no trae ``ValidNoticeInfo`` (caso golden 24).
- Los importes de una adjudicación y de una garantía a ``0`` se guardaban como
  ``0``: un contrato gratis, una baja del 100 %, una garantía del 0 %.
- El NUTS ``ES`` (nivel país) dejaba ``provincia`` = «España».
"""

from __future__ import annotations

import textwrap
from typing import Any

import pytest
from lxml import etree

from scraper.codice_parser import (
    parse_adjudicaciones,
    parse_condiciones,
    parse_entry,
    parse_entry_unfiltered,
)
from shared.geo import es_nuts_de_pais

_CBC = "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
_CAC = "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
_CACEXT = "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2"
_CBCEXT = "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2"

_UPDATED = "2026-10-23T17:06:21.032+02:00"


def _entry(
    *,
    issue_date: str | None = None,
    nuts: str = "ES300",
    subentity: str = "Madrid",
    cfs_extra: str = "",
) -> Any:
    """Entry SAP mínima, con el ``updated`` de la forma real (milisegundos y offset)."""
    valid_notice = (
        "<cacext:ValidNoticeInfo><cacext:AdditionalPublicationStatus>"
        "<cacext:AdditionalPublicationDocumentReference>"
        f"<cbc:IssueDate>{issue_date}</cbc:IssueDate>"
        "</cacext:AdditionalPublicationDocumentReference>"
        "</cacext:AdditionalPublicationStatus></cacext:ValidNoticeInfo>"
        if issue_date
        else ""
    )
    xml = textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{_CBC}" xmlns:cac="{_CAC}"
               xmlns:cacext="{_CACEXT}" xmlns:cbcext="{_CBCEXT}">
          <id>https://example.com/NI-001</id>
          <title>Mantenimiento SAP ERP</title>
          <updated>{_UPDATED}</updated>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>NI-001</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>ADJ</cbcext:ContractFolderStatusCode>
            <cac:ProcurementProject>
              <cbc:Name>Mantenimiento SAP ERP</cbc:Name>
              <cac:RequiredCommodityClassification>
                <cbc:ItemClassificationCode>72267100</cbc:ItemClassificationCode>
              </cac:RequiredCommodityClassification>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">100000</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
              <cac:RealizedLocation>
                <cbc:CountrySubentity>{subentity}</cbc:CountrySubentity>
                <cbc:CountrySubentityCode>{nuts}</cbc:CountrySubentityCode>
              </cac:RealizedLocation>
            </cac:ProcurementProject>
            {cfs_extra}
            {valid_notice}
          </cacext:ContractFolderStatus>
        </entry>
    """)
    return etree.fromstring(xml.encode())


def _tender_result(
    *, importe: str, pagable: str, minima: str, maxima: str, nif: str = "B12345678"
) -> str:
    return (
        "<cac:TenderResult>"
        "<cbc:ReceivedTenderQuantity>1</cbc:ReceivedTenderQuantity>"
        f"<cbc:LowerTenderAmount>{minima}</cbc:LowerTenderAmount>"
        f"<cbc:HigherTenderAmount>{maxima}</cbc:HigherTenderAmount>"
        "<cac:WinningParty>"
        f"<cac:PartyIdentification><cbc:ID>{nif}</cbc:ID></cac:PartyIdentification>"
        "<cac:PartyName><cbc:Name>Empresa SL</cbc:Name></cac:PartyName>"
        "</cac:WinningParty>"
        "<cac:AwardedTenderedProject><cac:LegalMonetaryTotal>"
        f"<cbc:TaxExclusiveAmount currencyID='EUR'>{importe}</cbc:TaxExclusiveAmount>"
        f"<cbc:PayableAmount currencyID='EUR'>{pagable}</cbc:PayableAmount>"
        "</cac:LegalMonetaryTotal></cac:AwardedTenderedProject>"
        "</cac:TenderResult>"
    )


def _garantia(*, tipo: str, rate: str | None, importe: str | None) -> str:
    rate_xml = f"<cbc:AmountRate>{rate}</cbc:AmountRate>" if rate is not None else ""
    importe_xml = (
        f"<cbc:LiabilityAmount currencyID='EUR'>{importe}</cbc:LiabilityAmount>"
        if importe is not None
        else ""
    )
    return (
        "<cac:RequiredFinancialGuarantee>"
        f"<cbc:GuaranteeTypeCode>{tipo}</cbc:GuaranteeTypeCode>{rate_xml}{importe_xml}"
        "</cac:RequiredFinancialGuarantee>"
    )


# ── fecha_publicacion sin ValidNoticeInfo ────────────────────────────────────


@pytest.mark.parametrize("parse", [parse_entry, parse_entry_unfiltered])
def test_sin_valid_notice_info_la_fecha_es_el_dia_del_updated(parse: Any) -> None:
    lic = parse(_entry())
    assert lic is not None
    assert lic.fecha_publicacion == "2026-10-23"
    # El timestamp completo no se pierde: es la fecha de actualización de la fuente.
    assert lic.fecha_actualizacion_fuente == _UPDATED


@pytest.mark.parametrize("parse", [parse_entry, parse_entry_unfiltered])
def test_issue_date_sigue_ganando_al_updated(parse: Any) -> None:
    lic = parse(_entry(issue_date="2026-09-30"))
    assert lic is not None
    assert lic.fecha_publicacion == "2026-09-30"


# ── importes a 0 = no informado ──────────────────────────────────────────────


def test_adjudicacion_con_importes_a_cero_los_deja_en_none() -> None:
    entry = _entry(cfs_extra=_tender_result(importe="0", pagable="0.00", minima="0", maxima="0"))
    [adj] = parse_adjudicaciones(entry, "NI-001")
    assert adj.importe_adjudicado is None
    assert adj.importe_pagable is None
    assert adj.oferta_minima is None
    assert adj.oferta_maxima is None
    # Lo que sí viene informado no se toca.
    assert adj.nombre == "Empresa SL"
    assert adj.n_ofertas_recibidas == 1


def test_adjudicacion_con_importes_informados_los_conserva() -> None:
    entry = _entry(
        cfs_extra=_tender_result(
            importe="47000.5", pagable="56870.61", minima="40000", maxima="55000"
        )
    )
    [adj] = parse_adjudicaciones(entry, "NI-001")
    assert adj.importe_adjudicado == 47000.5
    assert adj.importe_pagable == 56870.61
    assert adj.oferta_minima == 40000.0
    assert adj.oferta_maxima == 55000.0


def test_garantia_a_cero_queda_sin_porcentaje_ni_importe() -> None:
    terms = (
        "<cac:TenderingTerms>"
        + _garantia(tipo="1", rate="0", importe="0")
        + _garantia(tipo="2", rate="5", importe=None)
        + _garantia(tipo="3", rate=None, importe="1500")
        + "</cac:TenderingTerms>"
    )
    garantias = parse_condiciones(_entry(cfs_extra=terms)).garantias

    cero, porcentaje, importe = garantias
    # El código sí se publicó: la fila se queda, sin cifras inventadas.
    assert cero.tipo_codigo == "1"
    assert cero.porcentaje is None
    assert cero.importe is None
    assert cero.moneda is None  # sin importe, la moneda no describe nada

    assert porcentaje.porcentaje == 5.0
    assert importe.importe == 1500.0
    assert importe.moneda == "EUR"


def test_garantia_a_cero_sin_codigo_no_produce_fila() -> None:
    terms = (
        "<cac:TenderingTerms><cac:RequiredFinancialGuarantee>"
        "<cbc:AmountRate>0</cbc:AmountRate>"
        "</cac:RequiredFinancialGuarantee></cac:TenderingTerms>"
    )
    assert parse_condiciones(_entry(cfs_extra=terms)).garantias == []


# ── NUTS de nivel país ───────────────────────────────────────────────────────


@pytest.mark.parametrize("parse", [parse_entry, parse_entry_unfiltered])
def test_nuts_de_pais_no_da_provincia(parse: Any) -> None:
    lic = parse(_entry(nuts="ES", subentity="España"))
    assert lic is not None
    assert lic.provincia is None
    assert lic.ccaa is None
    assert lic.nuts_code == "ES"


@pytest.mark.parametrize("parse", [parse_entry, parse_entry_unfiltered])
def test_nuts_de_provincia_conserva_provincia_y_ccaa(parse: Any) -> None:
    lic = parse(_entry(nuts="ES300", subentity="Madrid"))
    assert lic is not None
    assert lic.provincia == "Madrid"
    assert lic.ccaa == "Madrid"


@pytest.mark.parametrize(
    ("nuts", "esperado"),
    [
        ("ES", True),
        (" es ", True),
        ("PT", True),
        ("ES3", False),
        ("ES30", False),
        ("ES300", False),
        ("", False),
        (None, False),
    ],
)
def test_es_nuts_de_pais(nuts: str | None, esperado: bool) -> None:
    assert es_nuts_de_pais(nuts) is esperado
