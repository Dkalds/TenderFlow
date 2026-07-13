"""_PlacspParseCore.parse_entry_elem propaga ParsedTender.documentos (F6, plan Pliegos+RAG).

Reutiliza el mismo estilo de fixture de ``test_codice_parser.py`` (namespaces
reales de CODICE, distintos de los de ``test_placsp_connector_parity.py``,
que usa URIs UBL genéricas suficientes solo para su propio test de paridad de
contrato — no ejercitan el XPath estructurado de ``cacext:ContractFolderStatus``).
"""

from __future__ import annotations

import textwrap

from lxml import etree

from scraper.connectors.placsp import _PlacspParseCore

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "cbc": "urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2",
    "cacext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2",
    "cbcext": "urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonBasicComponents-2",
}


def _sap_entry_with_documentos(id_externo: str = "EXP-DOC-001") -> str:
    cbc, cac, cacext, cbcext = _NS["cbc"], _NS["cac"], _NS["cacext"], _NS["cbcext"]
    return textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{cbc}"
               xmlns:cac="{cac}"
               xmlns:cacext="{cacext}"
               xmlns:cbcext="{cbcext}">
          <id>https://example.com/{id_externo}</id>
          <title>Mantenimiento SAP con pliegos</title>
          <updated>2026-07-01T00:00:00Z</updated>
          <summary>
            Id licitación: {id_externo}; Órgano de Contratación: Ministerio;
            Importe: 100000.00 EUR; Estado: PUB
          </summary>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>{id_externo}</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
            <cacext:LocatedContractingParty>
              <cac:Party>
                <cac:PartyName><cbc:Name>Ministerio</cbc:Name></cac:PartyName>
              </cac:Party>
            </cacext:LocatedContractingParty>
            <cac:ProcurementProject>
              <cbc:Name>Mantenimiento SAP con pliegos</cbc:Name>
              <cac:RequiredCommodityClassification>
                <cbc:ItemClassificationCode>72267100</cbc:ItemClassificationCode>
              </cac:RequiredCommodityClassification>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">100000.00</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
            </cac:ProcurementProject>
            <cac:LegalDocumentReference>
              <cbc:ID>1</cbc:ID>
              <cac:Attachment>
                <cac:ExternalReference>
                  <cbc:URI>https://contrataciondelestado.es/pcap.pdf</cbc:URI>
                  <cbc:FileName>PCAP.pdf</cbc:FileName>
                </cac:ExternalReference>
              </cac:Attachment>
            </cac:LegalDocumentReference>
            <cac:TechnicalDocumentReference>
              <cbc:ID>2</cbc:ID>
              <cac:Attachment>
                <cac:ExternalReference>
                  <cbc:URI>https://contrataciondelestado.es/ptt.pdf</cbc:URI>
                </cac:ExternalReference>
              </cac:Attachment>
            </cac:TechnicalDocumentReference>
          </cacext:ContractFolderStatus>
        </entry>
    """)


def _get_entry(entry_xml: str):
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n' + entry_xml + "\n</feed>\n"
    )
    root = etree.fromstring(feed.encode())
    return root.find("{http://www.w3.org/2005/Atom}entry")


def test_parse_entry_elem_populates_documentos():
    entry = _get_entry(_sap_entry_with_documentos())
    core = _PlacspParseCore()

    parsed = core.parse_entry_elem(entry, fuente="placsp")

    assert parsed is not None
    assert len(parsed.documentos) == 2
    tipos = {d.tipo for d in parsed.documentos}
    assert tipos == {"legal", "technical"}
    legal = next(d for d in parsed.documentos if d.tipo == "legal")
    assert legal.uri == "https://contrataciondelestado.es/pcap.pdf"
    assert legal.filename == "PCAP.pdf"


def test_parse_entry_elem_no_documentos_returns_empty_list():
    entry_xml = textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{_NS["cbc"]}"
               xmlns:cac="{_NS["cac"]}"
               xmlns:cacext="{_NS["cacext"]}"
               xmlns:cbcext="{_NS["cbcext"]}">
          <id>https://example.com/EXP-NODOC</id>
          <title>Mantenimiento SAP sin pliegos</title>
          <summary>
            Id licitación: EXP-NODOC; Órgano de Contratación: Ministerio;
            Importe: 50000.00 EUR; Estado: PUB
          </summary>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>EXP-NODOC</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
            <cac:ProcurementProject>
              <cbc:Name>Mantenimiento SAP sin pliegos</cbc:Name>
              <cac:RequiredCommodityClassification>
                <cbc:ItemClassificationCode>72267100</cbc:ItemClassificationCode>
              </cac:RequiredCommodityClassification>
            </cac:ProcurementProject>
          </cacext:ContractFolderStatus>
        </entry>
    """)
    entry = _get_entry(entry_xml)
    core = _PlacspParseCore()

    parsed = core.parse_entry_elem(entry, fuente="placsp")

    assert parsed is not None
    assert parsed.documentos == []
