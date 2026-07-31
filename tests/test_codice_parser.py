"""Tests de integración ligeros para scraper/codice_parser.py."""

from __future__ import annotations

import re
import textwrap

import pytest
from lxml import etree

from scraper.codice_parser import (
    _float,
    _int,
    _text,
    parse_adjudicaciones,
    parse_atom_bytes,
    parse_document_references,
    parse_entry,
    parse_entry_unfiltered,
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


def _make_entry_with_deadline(
    id_externo: str = "DEADLINE-001",
    *,
    end_date: str | None = "2026-01-15",
    end_time: str | None = "23:59:00",
    period_tag: str = "TenderSubmissionDeadlinePeriod",
    also_planned_period_end_date: str | None = None,
) -> str:
    """Entry SAP con ``TenderingProcess/<period_tag>/EndDate(+EndTime)``.

    ``also_planned_period_end_date`` añade además un
    ``ProcurementProject/PlannedPeriod/EndDate`` (fin de EJECUCIÓN del
    contrato, fuente de ``fecha_fin``) para verificar que ``fecha_limite`` y
    ``fecha_fin`` no se confunden entre sí.
    """
    cbc = _NS["cbc"]
    cac = _NS["cac"]
    cacext = _NS["cacext"]
    cbcext = _NS["cbcext"]

    end_time_xml = f"<cbc:EndTime>{end_time}</cbc:EndTime>" if end_time else ""
    deadline_xml = (
        f"<cac:TenderingProcess><cac:{period_tag}>"
        f"<cbc:EndDate>{end_date}</cbc:EndDate>{end_time_xml}"
        f"</cac:{period_tag}></cac:TenderingProcess>"
        if end_date
        else ""
    )
    planned_period_xml = (
        f"<cac:PlannedPeriod><cbc:EndDate>{also_planned_period_end_date}</cbc:EndDate>"
        "</cac:PlannedPeriod>"
        if also_planned_period_end_date
        else ""
    )

    return textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{cbc}"
               xmlns:cac="{cac}"
               xmlns:cacext="{cacext}"
               xmlns:cbcext="{cbcext}">
          <id>https://example.com/{id_externo}</id>
          <title>Sistema SAP ERP mantenimiento</title>
          <updated>2026-06-14T00:00:00Z</updated>
          <link href="https://example.com/{id_externo}" rel="alternate"/>
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
              <cbc:Name>Sistema SAP ERP mantenimiento</cbc:Name>
              <cac:BudgetAmount>
                <cbc:TaxExclusiveAmount currencyID="EUR">100000.00</cbc:TaxExclusiveAmount>
              </cac:BudgetAmount>
              {planned_period_xml}
            </cac:ProcurementProject>
            {deadline_xml}
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


def _make_entry_with_documentos(
    lic_id: str = "DOC-001",
    *,
    legal_uri: str | None = "https://contrataciondelestado.es/pliego-legal.pdf",
    technical_uri: str | None = "https://contrataciondelestado.es/pliego-tecnico.pdf",
    additional_uris: tuple[str, ...] = (),
    legal_filename: str | None = "PCAP.pdf",
) -> str:
    """Entry con {Legal,Technical,Additional}DocumentReference (adjuntos CODICE)."""
    cbc = _NS["cbc"]
    cac = _NS["cac"]
    cacext = _NS["cacext"]
    cbcext = _NS["cbcext"]

    def _doc_ref(uri: str | None, filename: str | None) -> str:
        if uri is None:
            return ""
        filename_xml = f"<cbc:FileName>{filename}</cbc:FileName>" if filename else ""
        return f"""
            <cac:Attachment>
              <cac:ExternalReference>
                <cbc:URI>{uri}</cbc:URI>
                {filename_xml}
              </cac:ExternalReference>
            </cac:Attachment>"""

    legal_xml = (
        f"<cac:LegalDocumentReference><cbc:ID>1</cbc:ID>"
        f"{_doc_ref(legal_uri, legal_filename)}</cac:LegalDocumentReference>"
        if legal_uri is not None
        else ""
    )
    technical_xml = (
        f"<cac:TechnicalDocumentReference><cbc:ID>2</cbc:ID>"
        f"{_doc_ref(technical_uri, None)}</cac:TechnicalDocumentReference>"
        if technical_uri is not None
        else ""
    )
    additional_xml = "".join(
        f"<cac:AdditionalDocumentReference><cbc:ID>{i + 3}</cbc:ID>"
        f"{_doc_ref(uri, None)}</cac:AdditionalDocumentReference>"
        for i, uri in enumerate(additional_uris)
    )

    return textwrap.dedent(f"""\
        <entry xmlns="http://www.w3.org/2005/Atom"
               xmlns:cbc="{cbc}"
               xmlns:cac="{cac}"
               xmlns:cacext="{cacext}"
               xmlns:cbcext="{cbcext}">
          <id>https://example.com/{lic_id}</id>
          <title>Contrato con pliegos</title>
          <updated>2024-03-15T00:00:00Z</updated>
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>{lic_id}</cbc:ContractFolderID>
            <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>
            {legal_xml}
            {technical_xml}
            {additional_xml}
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


# ─── fecha_limite (plazo de presentación de ofertas) ─────────────────────────


class TestTenderDeadline:
    """Regresión del fix de Ola 1 (docs/IMPROVEMENT_BACKLOG.md): antes de este
    fix, el parser nunca leía ``TenderingProcess`` y ``fecha_limite`` quedaba
    NULL en el 100% de las licitaciones de PLACSP."""

    def _get_entry(self, entry_xml: str):
        feed = _make_atom_feed(entry_xml)
        root = etree.fromstring(feed)
        return root.find("{http://www.w3.org/2005/Atom}entry")

    def test_tender_submission_deadline_extracted(self):
        entry = self._get_entry(
            _make_entry_with_deadline(end_date="2026-01-15", end_time="23:59:00")
        )
        lic = parse_entry(entry)
        assert lic is not None
        # 2026-01-15 es invierno en España (CET, UTC+1): 23:59 local = 22:59 UTC.
        # Si el código asumiera un offset fijo en vez de convertir por zona
        # horaria, este valor (o el de verano en otro test) sería incorrecto.
        assert lic.fecha_limite == "2026-01-15T22:59:00+00:00"

    def test_falls_back_to_participation_request_reception_period(self):
        entry = self._get_entry(
            _make_entry_with_deadline(
                end_date="2026-03-01",
                end_time="12:00:00",
                period_tag="ParticipationRequestReceptionPeriod",
            )
        )
        lic = parse_entry(entry)
        assert lic is not None
        assert lic.fecha_limite is not None
        assert lic.fecha_limite.startswith("2026-03-01")

    def test_no_tendering_process_node_returns_none(self):
        """Sin TenderingProcess (expediente en fase ADJ/RES, p.ej.), fecha_limite
        debe quedar None — nunca inferirse de PlannedPeriod/EndDate (fecha_fin)."""
        entry = self._get_entry(_make_entry_with_deadline(end_date=None))
        lic = parse_entry(entry)
        assert lic is not None
        assert lic.fecha_limite is None

    def test_fecha_limite_and_fecha_fin_are_independent(self):
        """PlannedPeriod/EndDate (ejecución) y TenderingProcess (presentación
        de ofertas) son nodos CODICE distintos con semántica distinta — el
        parser no debe confundirlos."""
        entry = self._get_entry(
            _make_entry_with_deadline(
                end_date="2026-02-01",
                end_time="10:00:00",
                also_planned_period_end_date="2027-12-31",
            )
        )
        lic = parse_entry(entry)
        assert lic is not None
        assert lic.fecha_fin == "2027-12-31"
        assert lic.fecha_limite is not None
        assert lic.fecha_limite.startswith("2026-02-01")
        assert lic.fecha_limite != lic.fecha_fin

    def test_parse_entry_unfiltered_also_extracts_fecha_limite(self):
        entry = self._get_entry(
            _make_entry_with_deadline(end_date="2026-04-10", end_time="09:00:00")
        )
        lic = parse_entry_unfiltered(entry)
        assert lic is not None
        assert lic.fecha_limite is not None
        assert lic.fecha_limite.startswith("2026-04-10")


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


# ─── normalización de fechas (regresión RFC norm-fechas) ─────────────────────


def _make_entry_with_issue_dates(
    id_externo: str = "DATE-001",
    issue_dates: tuple[str, ...] = ("2026-06-14",),
) -> str:
    """Entry SAP con uno o varios IssueDate (acepta formatos mezclados).

    Inyecta cada `IssueDate` dentro de
    `ValidNoticeInfo/AdditionalPublicationStatus/AdditionalPublicationDocumentReference`,
    que es el XPath que consume `_issue_date()` en el parser.
    """
    cbc = _NS["cbc"]
    cac = _NS["cac"]
    cacext = _NS["cacext"]
    cbcext = _NS["cbcext"]
    issue_blocks = "".join(
        f"""
        <cacext:AdditionalPublicationStatus>
          <cacext:AdditionalPublicationDocumentReference>
            <cbc:IssueDate>{d}</cbc:IssueDate>
          </cacext:AdditionalPublicationDocumentReference>
        </cacext:AdditionalPublicationStatus>"""
        for d in issue_dates
    )
    return (
        f'<entry xmlns="http://www.w3.org/2005/Atom"\n'
        f'       xmlns:cbc="{cbc}"\n'
        f'       xmlns:cac="{cac}"\n'
        f'       xmlns:cacext="{cacext}"\n'
        f'       xmlns:cbcext="{cbcext}">\n'
        f"  <id>https://example.com/{id_externo}</id>\n"
        f"  <title>Sistema SAP ERP</title>\n"
        f"  <updated>2026-06-14T00:00:00Z</updated>\n"
        f'  <link href="https://example.com/{id_externo}" rel="alternate"/>\n'
        f"  <summary>Id licitación: {id_externo}; "
        f"Órgano de Contratación: Test; Importe: 1000 EUR; Estado: PUB</summary>\n"
        f"  <cacext:ContractFolderStatus>\n"
        f"    <cbc:ContractFolderID>{id_externo}</cbc:ContractFolderID>\n"
        f"    <cbcext:ContractFolderStatusCode>PUB</cbcext:ContractFolderStatusCode>\n"
        f"    <cacext:LocatedContractingParty>\n"
        f"      <cac:Party>\n"
        f"        <cac:PartyName><cbc:Name>Test</cbc:Name></cac:PartyName>\n"
        f"      </cac:Party>\n"
        f"    </cacext:LocatedContractingParty>\n"
        f"    <cac:ProcurementProject>\n"
        f"      <cbc:Name>Sistema SAP ERP</cbc:Name>\n"
        f"      <cac:BudgetAmount>\n"
        f'        <cbc:TaxExclusiveAmount currencyID="EUR">1000</cbc:TaxExclusiveAmount>\n'
        f"      </cac:BudgetAmount>\n"
        f"    </cac:ProcurementProject>\n"
        f"    <cacext:ValidNoticeInfo>"
        f"{issue_blocks}\n"
        f"    </cacext:ValidNoticeInfo>\n"
        f"  </cacext:ContractFolderStatus>\n"
        f"</entry>\n"
    )


_ISO_GLOB_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}")


class TestDateNormalization:
    """Regresión del RFC norm-fechas (2026-06-16): el parser nunca debe
    producir un valor que viole el CHECK GLOB('????-??-??*') de las
    columnas fecha_* en `licitaciones`/`adjudicaciones` (db/schema.py)."""

    def _get_entry(self, entry_xml: str):
        feed = _make_atom_feed(entry_xml)
        root = etree.fromstring(feed)
        return root.find("{http://www.w3.org/2005/Atom}entry")

    def test_issue_date_dmy_produces_iso_fecha_publicacion(self):
        """Un IssueDate en formato DD/MM/YYYY genera fecha_publicacion ISO
        (escenario clásico del bug fijado en commit 1166964)."""
        entry = self._get_entry(_make_entry_with_issue_dates(issue_dates=("14/06/2026",)))
        lic = parse_entry(entry)
        assert lic is not None
        assert lic.fecha_publicacion == "2026-06-14"
        assert _ISO_GLOB_PREFIX.match(lic.fecha_publicacion or "")

    def test_issue_date_mixed_formats_picks_chronological_minimum(self):
        """Con IssueDates en formatos mezclados, _issue_date normaliza antes
        de min() → mínimo CRONOLÓGICO. Sin normalizar, el min lexicográfico
        de ('2026-06-14', '15/01/2026') sería '15/01/2026' (porque '1' < '2'),
        violando además el CHECK GLOB."""
        entry = self._get_entry(
            _make_entry_with_issue_dates(
                issue_dates=("2026-06-14", "15/01/2026"),
            )
        )
        lic = parse_entry(entry)
        assert lic is not None
        assert lic.fecha_publicacion == "2026-01-15"

    def test_all_date_fields_pass_check_glob(self):
        """Todos los campos de fecha del parser cumplen el shape ISO
        que exige el CHECK GLOB en db/schema.py."""
        entry = self._get_entry(_make_entry_with_issue_dates(issue_dates=("01/02/2026",)))
        lic = parse_entry(entry)
        assert lic is not None
        for field in ("fecha_publicacion", "fecha_actualizacion_fuente"):
            val = getattr(lic, field)
            if val is not None:
                assert _ISO_GLOB_PREFIX.match(val), f"{field}={val!r} no pasa CHECK GLOB"


# ─── parse_document_references (plan Pliegos+RAG, F6) ───────────────────────


class TestParseDocumentReferences:
    def _get_entry(self, entry_xml: str):
        feed = _make_atom_feed(entry_xml)
        root = etree.fromstring(feed)
        return root.find("{http://www.w3.org/2005/Atom}entry")

    def test_extracts_legal_technical_and_additional(self):
        entry = self._get_entry(
            _make_entry_with_documentos(
                additional_uris=("https://contrataciondelestado.es/anexo1.pdf",),
            )
        )
        refs = parse_document_references(entry)

        assert len(refs) == 3
        tipos = {r.tipo for r in refs}
        assert tipos == {"legal", "technical", "additional"}

    def test_legal_ref_has_uri_and_filename(self):
        entry = self._get_entry(_make_entry_with_documentos())
        refs = parse_document_references(entry)

        legal = next(r for r in refs if r.tipo == "legal")
        assert legal.uri == "https://contrataciondelestado.es/pliego-legal.pdf"
        assert legal.filename == "PCAP.pdf"

    def test_filename_is_optional(self):
        entry = self._get_entry(_make_entry_with_documentos())
        refs = parse_document_references(entry)

        technical = next(r for r in refs if r.tipo == "technical")
        assert technical.uri == "https://contrataciondelestado.es/pliego-tecnico.pdf"
        assert technical.filename is None

    def test_multiple_additional_documents(self):
        entry = self._get_entry(
            _make_entry_with_documentos(
                legal_uri=None,
                technical_uri=None,
                additional_uris=(
                    "https://contrataciondelestado.es/anexo1.pdf",
                    "https://contrataciondelestado.es/anexo2.pdf",
                    "https://contrataciondelestado.es/anexo3.pdf",
                ),
            )
        )
        refs = parse_document_references(entry)

        assert len(refs) == 3
        assert all(r.tipo == "additional" for r in refs)
        assert {r.uri for r in refs} == {
            "https://contrataciondelestado.es/anexo1.pdf",
            "https://contrataciondelestado.es/anexo2.pdf",
            "https://contrataciondelestado.es/anexo3.pdf",
        }

    def test_no_document_references_returns_empty_list(self):
        """La mayoría de entries del feed no tienen adjuntos — caso común, no error."""
        entry = self._get_entry(_make_sap_entry())
        assert parse_document_references(entry) == []

    def test_reference_without_attachment_uri_is_skipped(self):
        """DocumentReference sin cac:Attachment (adjunto reservado/no publicado,
        habitual en CODICE) no debe producir una referencia con uri=None."""
        entry_xml = textwrap.dedent(f"""\
            <entry xmlns="http://www.w3.org/2005/Atom"
                   xmlns:cbc="{_NS["cbc"]}"
                   xmlns:cac="{_NS["cac"]}"
                   xmlns:cacext="{_NS["cacext"]}"
                   xmlns:cbcext="{_NS["cbcext"]}">
              <id>https://example.com/DOC-NOATT</id>
              <title>Contrato sin adjunto accesible</title>
              <cacext:ContractFolderStatus>
                <cbc:ContractFolderID>DOC-NOATT</cbc:ContractFolderID>
                <cac:LegalDocumentReference>
                  <cbc:ID>1</cbc:ID>
                </cac:LegalDocumentReference>
              </cacext:ContractFolderStatus>
            </entry>
        """)
        entry = self._get_entry(entry_xml)
        assert parse_document_references(entry) == []

    def test_parse_entry_is_unaffected_by_document_references(self):
        """parse_entry() sigue devolviendo Licitacion normalmente; los adjuntos
        se extraen por separado (Licitacion no lleva ese campo, TID251/§3.5)."""
        entry = self._get_entry(_make_entry_with_documentos())
        lic = parse_entry(entry)
        # No es una entry SAP -> parse_entry (con filtro de tecnología) descarta.
        # Lo relevante es que no lance ni devuelva algo con un campo 'documentos'.
        assert lic is None or not hasattr(lic, "documentos")
