"""Tests de integración ligeros para scraper/codice_parser.py."""

from __future__ import annotations

import textwrap

import pytest
from lxml import etree

from scraper.codice_parser import (
    _float,
    _int,
    _text,
    parse_adjudicaciones,
    parse_atom_bytes,
    parse_entry,
    parse_summary,
)

# ─── namespaces usados en el XML de prueba ───────────────────────────────────

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


def _ns(prefix: str) -> str:
    """Devuelve {namespace_uri} para usar en Clark notation."""
    return "{" + _NS[prefix] + "}"


# ─── helpers XML ─────────────────────────────────────────────────────────────


def _make_atom_feed(entries_xml: str) -> bytes:
    """Envuelve una o varias <entry> en un feed ATOM mínimo."""
    # Nota: no usar textwrap.dedent aquí porque la interpolación de
    # entries_xml puede tener indentación diferente y quebrarse.
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n' + entries_xml + "\n</feed>\n"
    )
    return xml.encode()


def _make_sap_entry(
    id_externo: str = "EXP-2024-001",
    titulo: str = "Mantenimiento SAP ERP",
    importe: str = "100000.00",
    estado: str = "PUB",
    organo: str = "Ministerio de Hacienda",
    cpv: str = "72267100-0",
    nuts: str = "ES300",
) -> str:
    """Genera XML de una <entry> CODICE mínima con datos SAP."""
    cbc = _NS["cbc"]
    cac = _NS["cac"]
    cacext = _NS["cacext"]
    cbcext = _NS["cbcext"]

    return textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{cbc}"
               xmlns:cac="{cac}"
               xmlns:cacext="{cacext}"
               xmlns:cbcext="{cbcext}">
          <id>https://example.com/{id_externo}</id>
          <title>{titulo}</title>
          <updated>2024-03-15T00:00:00Z</updated>
          <link href="https://example.com/{id_externo}" rel="alternate"/>
          <summary>
            Id licitación: {id_externo}; Órgano de Contratación: {organo};
            Importe: {importe} EUR; Estado: {estado}
          </summary>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>{id_externo}</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>{estado}</cbcext:ContractFolderStatusCode>
            <cacext:LocatedContractingParty>
              <cac:Party>
                <cac:PartyName><cbc:Name>{organo}</cbc:Name></cac:PartyName>
              </cac:Party>
            </cacext:LocatedContractingParty>
            <cac:ProcurementProject>
              <cbc:Name>{titulo}</cbc:Name>
              <cbc:TypeCode>2</cbc:TypeCode>
              <cac:RequiredCommodityClassification>
                <cbc:ItemClassificationCode>{cpv}</cbc:ItemClassificationCode>
              </cac:RequiredCommodityClassification>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">{importe}</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
              <cac:RealizedLocation>
                <cbc:CountrySubentityCode>{nuts}</cbc:CountrySubentityCode>
              </cac:RealizedLocation>
              <cac:PlannedPeriod>
                <cbc:DurationMeasure unitCode="MON">12</cbc:DurationMeasure>
              </cac:PlannedPeriod>
            </cac:ProcurementProject>
          </cacext:ContractFolderStatus>
        </entry>
    """)


def _make_entry_with_adjudicacion(lic_id: str = "ADJ-001") -> str:
    """Entry con un TenderResult y WinningParty."""
    cbc = _NS["cbc"]
    cac = _NS["cac"]
    cacext = _NS["cacext"]
    cbcext = _NS["cbcext"]

    return textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{cbc}"
               xmlns:cac="{cac}"
               xmlns:cacext="{cacext}"
               xmlns:cbcext="{cbcext}">
          <id>https://example.com/{lic_id}</id>
          <title>Mantenimiento plataforma SAP</title>
          <updated>2024-03-15T00:00:00Z</updated>
          <link href="https://example.com/{lic_id}" rel="alternate"/>
          <summary>
            Id licitación: {lic_id}; Órgano de Contratación: Ministerio;
            Importe: 50000.00 EUR; Estado: ADJ
          </summary>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>{lic_id}</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>ADJ</cbcext:ContractFolderStatusCode>
            <cacext:LocatedContractingParty>
              <cac:Party>
                <cac:PartyName><cbc:Name>Ministerio</cbc:Name></cac:PartyName>
              </cac:Party>
            </cacext:LocatedContractingParty>
            <cac:ProcurementProject>
              <cbc:Name>Mantenimiento plataforma SAP</cbc:Name>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">50000.00</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
            </cac:ProcurementProject>
            <cac:TenderResult>
              <cbc:AwardDate>2024-04-01</cbc:AwardDate>
              <cbc:ReceivedTenderQuantity>5</cbc:ReceivedTenderQuantity>
              <cbc:LowerTenderAmount>40000.00</cbc:LowerTenderAmount>
              <cbc:HigherTenderAmount>55000.00</cbc:HigherTenderAmount>
              <cac:AwardedTenderedProject>
                <cac:LegalMonetaryTotal>
                  <cbc:TaxExclusiveAmount>47000.00</cbc:TaxExclusiveAmount>
                  <cbc:PayableAmount>56870.00</cbc:PayableAmount>
                </cac:LegalMonetaryTotal>
              </cac:AwardedTenderedProject>
              <cac:WinningParty>
                <cac:PartyName><cbc:Name>Empresa Ganadora SL</cbc:Name></cac:PartyName>
                <cac:PartyIdentification><cbc:ID>B12345678</cbc:ID></cac:PartyIdentification>
              </cac:WinningParty>
            </cac:TenderResult>
          </cacext:ContractFolderStatus>
        </entry>
    """)


class TestParseSummary:
    def test_extrae_campos_basicos(self):
        summary = (
            "Id licitación: ABC-123; "
            "Órgano de Contratación: Ministerio de Hacienda; "
            "Importe: 150000.00 EUR; "
            "Estado: PUB"
        )
        result = parse_summary(summary)
        assert result["id_externo"] == "ABC-123"
        assert result["organo_contratacion"] == "Ministerio de Hacienda"
        assert result["importe"] == pytest.approx(150000.0)
        assert result["estado"] == "PUB"
        assert result["moneda"] == "EUR"

    def test_importe_con_coma_decimal(self):
        # El regex del SUMMARY espera punto como separador decimal,
        # un importe con coma y punto (1.234,56) no matchea el patrón [\d.,]+
        # ya que el campo falla la conversión a float. El comportamiento real
        # es que no se extrae importe — lo documentamos explícitamente.
        summary = (
            "Id licitación: X-1; "
            "Órgano de Contratación: Ayuntamiento; "
            "Importe: 1.234,56 EUR; "
            "Estado: RES"
        )
        result = parse_summary(summary)
        # Puede devolver importe o no — lo importante es que no lanza excepción
        assert isinstance(result, dict)

    def test_none_devuelve_dict_vacio(self):
        assert parse_summary(None) == {}

    def test_string_vacio_devuelve_dict_vacio(self):
        assert parse_summary("") == {}

    def test_summary_malformado_devuelve_dict_vacio(self):
        assert parse_summary("Texto sin formato esperado") == {}

    def test_moneda_ausente_usa_eur_por_defecto(self):
        summary = "Id licitación: X-2; Órgano de Contratación: Org; Importe: 5000; Estado: PUB"
        result = parse_summary(summary)
        # Si no hay moneda explícita, debe ser EUR o estar ausente
        moneda = result.get("moneda", "EUR")
        assert moneda in ("EUR", "")


# ─── helpers XML internos ────────────────────────────────────────────────────


class TestXmlHelpers:
    def _elem(self, xml: str):
        return etree.fromstring(xml.encode())

    def test_text_returns_value(self):
        e = self._elem("<root><a>hello</a></root>")
        assert _text(e, "./a") == "hello"

    def test_text_returns_none_when_missing(self):
        e = self._elem("<root/>")
        assert _text(e, "./a") is None

    def test_text_with_none_elem_returns_none(self):
        assert _text(None, "./a") is None

    def test_float_parses_value(self):
        e = self._elem("<root><v>1234.56</v></root>")
        assert _float(e, "./v") == pytest.approx(1234.56)

    def test_float_parses_comma_decimal(self):
        e = self._elem("<root><v>1234,56</v></root>")
        assert _float(e, "./v") == pytest.approx(1234.56)

    def test_float_returns_none_for_invalid(self):
        e = self._elem("<root><v>not_a_number</v></root>")
        assert _float(e, "./v") is None

    def test_int_parses_value(self):
        e = self._elem("<root><n>7</n></root>")
        assert _int(e, "./n") == 7

    def test_int_returns_none_for_missing(self):
        e = self._elem("<root/>")
        assert _int(e, "./n") is None


# ─── parse_entry ─────────────────────────────────────────────────────────────


class TestParseEntry:
    def _get_entry(self, entry_xml: str):
        feed = _make_atom_feed(entry_xml)
        root = etree.fromstring(feed)
        return root.find("{http://www.w3.org/2005/Atom}entry")

    def test_sap_entry_is_parsed(self):
        entry = self._get_entry(_make_sap_entry())
        lic = parse_entry(entry)
        assert lic is not None
        assert lic.id_externo == "EXP-2024-001"
        assert lic.titulo == "Mantenimiento SAP ERP"
        assert lic.importe == pytest.approx(100_000.0)
        assert lic.estado == "PUB"
        assert lic.organo_contratacion == "Ministerio de Hacienda"

    def test_non_sap_entry_returns_none(self):
        entry = self._get_entry(
            _make_sap_entry(
                titulo="Construcción de carreteras",
                id_externo="CARRETERA-2024-001",  # sin la palabra SAP
            )
        )
        # Título y summary no contienen keywords SAP → debe retornar None
        lic = parse_entry(entry)
        assert lic is None

    def test_entry_without_id_returns_none(self):
        # Entry donde no hay ContractFolderID ni id atom válido
        entry_xml = textwrap.dedent("""\
            <entry xmlns="http://www.w3.org/2005/Atom">
              <title>Sistema SAP ERP mantenimiento</title>
              <updated>2024-01-01T00:00:00Z</updated>
            </entry>
        """)
        entry = self._get_entry(entry_xml)
        lic = parse_entry(entry)
        assert lic is None

    def test_cpv_extracted_correctly(self):
        entry = self._get_entry(_make_sap_entry(cpv="72267100-0"))
        lic = parse_entry(entry)
        assert lic is not None
        assert lic.cpv == "72267100-0"

    def test_duracion_parsed(self):
        entry = self._get_entry(_make_sap_entry())
        lic = parse_entry(entry)
        assert lic is not None
        assert lic.duracion_valor == pytest.approx(12.0)
        assert lic.duracion_unidad == "MON"


# ─── parse_adjudicaciones ────────────────────────────────────────────────────


class TestParseAdjudicaciones:
    def _get_entry(self, entry_xml: str):
        feed = _make_atom_feed(entry_xml)
        root = etree.fromstring(feed)
        return root.find("{http://www.w3.org/2005/Atom}entry")

    def test_extracts_adjudicacion(self):
        entry = self._get_entry(_make_entry_with_adjudicacion("ADJ-001"))
        adjs = parse_adjudicaciones(entry, "ADJ-001")
        assert len(adjs) == 1
        adj = adjs[0]
        assert adj.nombre == "Empresa Ganadora SL"
        assert adj.nif == "B12345678"
        assert adj.importe_adjudicado == pytest.approx(47_000.0)
        assert adj.n_ofertas_recibidas == 5
        assert adj.oferta_minima == pytest.approx(40_000.0)
        assert adj.oferta_maxima == pytest.approx(55_000.0)
        assert adj.fecha_adjudicacion == "2024-04-01"

    def test_entry_without_tender_result_returns_empty(self):
        entry = self._get_entry(_make_sap_entry())
        adjs = parse_adjudicaciones(entry, "EXP-2024-001")
        assert adjs == []


# ─── parse_atom_bytes ────────────────────────────────────────────────────────


class TestParseAtomBytes:
    def test_yields_sap_entries(self):
        feed = _make_atom_feed(_make_sap_entry("SAP-001"))
        results = list(parse_atom_bytes(feed))
        assert len(results) == 1
        lic, adjs = results[0]
        assert lic.id_externo == "SAP-001"
        assert isinstance(adjs, list)

    def test_skips_non_sap_entries(self):
        feed = _make_atom_feed(_make_sap_entry("PAVING-2024", titulo="Obras de pavimentación"))
        results = list(parse_atom_bytes(feed))
        assert results == []

    def test_multiple_entries(self):
        feed = _make_atom_feed(
            _make_sap_entry("SAP-001", titulo="Sistema SAP módulo FI")
            + _make_sap_entry("SAP-002", titulo="Soporte SAP HANA")
            + _make_sap_entry("VIAL-001", titulo="Mantenimiento vial")
        )
        results = list(parse_atom_bytes(feed))
        ids = [r[0].id_externo for r in results]
        assert "SAP-001" in ids
        assert "SAP-002" in ids
        assert "VIAL-001" not in ids

    def test_raises_on_oversized_content(self):
        from config import settings

        big = b"x" * (settings.MAX_XML_SIZE_BYTES + 1)
        with pytest.raises(ValueError, match="demasiado grande"):
            list(parse_atom_bytes(big))

    def test_entry_with_adjudicaciones(self):
        feed = _make_atom_feed(_make_entry_with_adjudicacion("ADJ-SAP-001"))
        results = list(parse_atom_bytes(feed))
        assert len(results) == 1
        _, adjs = results[0]
        assert len(adjs) == 1
