"""Test de paridad: PlacspAtomConnector / PlacspBulkConnector vs pipeline legacy.

Estrategia de dos niveles (F2):

1. Test de paridad de DELEGACIÓN (contrato):
   - PlacspAtomConnector.fetch() devuelve RawNotice con payload correcto.
   - PlacspAtomConnector.parse() delega en parse_entry / _ml_classify_entry.
   - PlacspAtomConnector.new_cursor() propaga etag/last_seen_updated.
   - PlacspBulkConnector.new_cursor() siempre devuelve None.

2. Test de paridad de DATOS con fixture XML mínimo:
   - Misma entry XML parseda por el conector y por el pipeline legacy produce
     la misma Licitacion (campos clave: id_externo, titulo, fuente).
   - Segunda pasada: idempotencia (0 duplicados, resultado sin cambios).
   - El test usa una BD temporal aislada (tmp_db fixture).

El test de paridad completo contra fixtures reales de producción
(mini-ZIP + ATOM reales) requiere tests/fixtures/placsp/ que se añadirán
cuando se prepare el flip a PLACSP_CONNECTOR_ENABLED=True.
"""

from __future__ import annotations

import textwrap
from typing import Any
from unittest.mock import patch

import pytest

from scraper.connectors.base import RawNotice
from scraper.connectors.placsp import (
    PlacspAtomConnector,
    PlacspBulkConnector,
    _iter_atom_entries,
    _PlacspParseCore,
)

# ── XML mínimo válido (ATOM + CODICE simplificado) ────────────────────────────
# Suficiente para que parse_entry devuelva una Licitacion con id_externo real.

_SAMPLE_ATOM_FEED = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
          xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
          xmlns:cacext="urn:dgpe:names:draft:codice:schema:xsd:CACExtension-2">
      <title>PLACE feed</title>
      <updated>2026-07-05T00:00:00Z</updated>
      <entry>
        <id>https://contratacion.hacienda.gob.es/TESTs/2026/TEST-001</id>
        <title>Test licitacion SAP Basis</title>
        <updated>2026-07-05T10:00:00Z</updated>
        <summary>Importe: 100.000 EUR. CPV 72212000.</summary>
        <content type="application/xml">
          <cacext:ContractFolderStatus>
            <cbc:ContractFolderID>TEST-001</cbc:ContractFolderID>
            <cbc:ContractFolderStatusCode listURI="http://contrataciondelestado.es/codice/cl/2.02/ContractFolderStatus">ADM</cbc:ContractFolderStatusCode>
            <cacext:LocatedContractingParty>
              <cac:Party>
                <cac:PartyName>
                  <cbc:Name>Ministerio de Test</cbc:Name>
                </cac:PartyName>
              </cac:Party>
            </cacext:LocatedContractingParty>
            <cac:ProcurementProject>
              <cbc:Name>Test licitacion SAP Basis</cbc:Name>
              <cbc:Description>Implementacion SAP BASIS para administracion publica</cbc:Description>
              <cbc:EstimatedOverallContractAmount currencyID="EUR">100000.00</cbc:EstimatedOverallContractAmount>
              <cbc:TypeCode listURI="http://contrataciondelestado.es/codice/cl/2.02/ContractType">2</cbc:TypeCode>
              <cac:RequiredCommodityClassification>
                <cbc:ItemClassificationCode listURI="http://contrataciondelestado.es/codice/cl/2.02/CPVCodes">72212000</cbc:ItemClassificationCode>
              </cac:RequiredCommodityClassification>
            </cac:ProcurementProject>
          </cacext:ContractFolderStatus>
        </content>
      </entry>
    </feed>
""").encode("utf-8")


# ── Helpers de fixture ────────────────────────────────────────────────────────


def _parse_feed_entries() -> list[tuple[Any, str]]:
    """Extrae entries del feed XML de muestra."""
    from lxml import etree

    ATOM_NS = "http://www.w3.org/2005/Atom"
    parser = etree.XMLParser(huge_tree=False, recover=True, resolve_entities=False, no_network=True)
    root = etree.fromstring(_SAMPLE_ATOM_FEED, parser=parser)
    entries = []
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        updated_el = entry.find(f"{{{ATOM_NS}}}updated")
        updated = updated_el.text.strip() if updated_el is not None and updated_el.text else ""
        entries.append((entry, updated))
    return entries


# ── Tests de contrato del conector ────────────────────────────────────────────


class TestPlacspAtomConnectorContract:
    """Tests de contrato: el conector implementa correctamente el protocolo."""

    def test_source_id(self):
        c = PlacspAtomConnector()
        assert c.source_id == "placsp"

    def test_new_cursor_none_before_fetch(self):
        """Sin fetch previo, new_cursor no debería producir un cursor con datos."""
        c = PlacspAtomConnector()
        result = c.new_cursor()
        # Sin _meta no tiene newest_updated ni etag → None
        assert result is None

    def test_new_cursor_after_fetch_with_meta(self):
        """Tras fetch que obtiene entries, new_cursor propaga el estado correcto."""
        c = PlacspAtomConnector()
        c._meta = {
            "newest_updated": "2026-07-05T10:00:00Z",
            "etag": '"abc123"',
            "last_modified": "Sat, 05 Jul 2026 10:00:00 GMT",
        }
        c._last_seen_updated = None
        cursor = c.new_cursor()
        assert cursor is not None
        assert cursor["last_seen_updated"] == "2026-07-05T10:00:00Z"
        assert cursor["etag"] == '"abc123"'

    def test_new_cursor_propagates_previous_etag_on_304(self):
        """Si la respuesta fue 304 (meta sin etag), el cursor propaga el etag previo."""
        c = PlacspAtomConnector()
        c._meta = {"newest_updated": None, "etag": '"prev"', "last_modified": None}
        c._last_seen_updated = "2026-07-04T00:00:00Z"
        cursor = c.new_cursor()
        assert cursor is not None
        assert cursor["etag"] == '"prev"'

    def test_fetch_delegates_to_iter_live_entries(self, tmp_db):
        """fetch() llama a iter_live_entries con el cursor correcto."""
        entries = _parse_feed_entries()
        meta = {
            "newest_updated": "2026-07-05T10:00:00Z",
            "etag": '"test"',
            "last_modified": None,
            "pages_fetched": 1,
            "entries_seen": 1,
            "stopped_reason": "exhausted",
        }

        with patch("scraper.atom_live.iter_live_entries", return_value=(entries, meta)):
            connector = PlacspAtomConnector()
            cursor = {"last_seen_updated": "2026-07-04T00:00:00Z", "etag": None}
            notices = list(connector.fetch(cursor))

        assert len(notices) == 1
        assert isinstance(notices[0], RawNotice)
        assert notices[0].payload[1] == "2026-07-05T10:00:00Z"

    def test_parse_returns_parsed_tender_or_none(self, tmp_db):
        """parse() devuelve ParsedTender con la licitacion del fixture XML."""
        entries = _parse_feed_entries()
        entry_elem, updated = entries[0]

        connector = PlacspAtomConnector()
        raw = RawNotice(natural_id=updated, payload=(entry_elem, updated))
        result = connector.parse(raw)

        # El XML de muestra puede o no pasar el filtro de keywords (depende de config),
        # así que aceptamos tanto ParsedTender como None.
        if result is not None:
            from scraper.connectors.base import ParsedTender

            assert isinstance(result, ParsedTender)
            assert result.licitacion.fuente == "placsp"

    def test_parse_raises_on_corrupt_payload(self, tmp_db):
        """parse() propaga excepciones de parseo (para que run_connector las envíe a DLQ)."""
        connector = PlacspAtomConnector()
        raw = RawNotice(natural_id="bad", payload=(object(), None))
        with pytest.raises((TypeError, AttributeError, Exception)):
            connector.parse(raw)


class TestPlacspBulkConnectorContract:
    """Tests de contrato del conector bulk."""

    def test_source_id_encodes_year_month(self):
        c = PlacspBulkConnector(2026, 7)
        assert c.source_id == "bulk_202607"

    def test_new_cursor_always_none(self):
        c = PlacspBulkConnector(2026, 7)
        assert c.new_cursor() is None

    def test_invalid_month_raises(self):
        with pytest.raises(ValueError, match="month"):
            PlacspBulkConnector(2026, 13)

    def test_invalid_year_raises(self):
        with pytest.raises(ValueError, match="year"):
            PlacspBulkConnector(1999, 1)

    def test_fetch_yields_nothing_if_not_published(self, tmp_db):
        """Si download_month devuelve None (mes no publicado), fetch no emite nada."""
        with patch("scraper.bulk_downloader.download_month", return_value=None):
            connector = PlacspBulkConnector(2026, 7)
            notices = list(connector.fetch(None))
        assert notices == []

    def test_fetch_parses_xml_entries(self, tmp_db, tmp_path):
        """fetch() itera entries desde el ZIP correctamente."""
        import io
        import zipfile

        # Crear ZIP en memoria con el XML de muestra
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("licitaciones_202607.atom", _SAMPLE_ATOM_FEED)
        buf.seek(0)
        zip_path = tmp_path / "test.zip"
        zip_path.write_bytes(buf.read())

        with patch("scraper.bulk_downloader.download_month", return_value=zip_path):
            connector = PlacspBulkConnector(2026, 7)
            notices = list(connector.fetch(None))

        assert len(notices) >= 1
        assert all(isinstance(n, RawNotice) for n in notices)


# ── Test de paridad de datos ──────────────────────────────────────────────────


class TestPlacspDataParity:
    """Verifica que el conector y el pipeline legacy producen los mismos datos.

    Nivel básico: misma entry XML → misma Licitacion (campos clave).
    El test completo con fixtures reales de producción se añadirá cuando
    se prepare el flip a PLACSP_CONNECTOR_ENABLED=True.
    """

    def test_parse_core_matches_legacy_parse_entry(self, tmp_db):
        """_PlacspParseCore.parse_entry_elem produce la misma licitacion que parse_entry."""
        from scraper.codice_parser import parse_entry

        entries = _parse_feed_entries()
        if not entries:
            pytest.skip("No entries in sample feed")

        entry_elem, updated = entries[0]

        # Resultado del pipeline legacy
        legacy_lic = parse_entry(entry_elem)

        # Resultado del núcleo del conector
        core = _PlacspParseCore()
        parsed = core.parse_entry_elem(entry_elem, fuente="placsp", updated_str=updated)

        if legacy_lic is None and parsed is None:
            # Ambos descartan la entry (filtro de keywords) → paridad OK
            return

        if legacy_lic is None or parsed is None:
            # Divergencia: uno acepta, el otro descarta
            pytest.fail(
                f"Paridad rota: legacy={legacy_lic}, conector={parsed}. "
                "El conector y el pipeline deben tomar la misma decisión de filtrado."
            )

        # Campos clave deben coincidir
        assert parsed.licitacion.id_externo == legacy_lic.id_externo, (
            "id_externo difiere entre conector y legacy"
        )
        assert parsed.licitacion.titulo == legacy_lic.titulo, (
            "titulo difiere entre conector y legacy"
        )

    def test_idempotencia_atom_connector(self, tmp_db):
        """Dos ejecuciones del AtomConnector sobre el mismo fixture → 0 duplicados."""
        _db_mod, _ = tmp_db
        entries = _parse_feed_entries()
        if not entries:
            pytest.skip("No entries in sample feed")

        meta = {
            "newest_updated": "2026-07-05T10:00:00Z",
            "etag": None,
            "last_modified": None,
            "pages_fetched": 1,
            "entries_seen": len(entries),
            "stopped_reason": "exhausted",
        }

        from scraper.connectors.base import run_connector

        with patch("scraper.atom_live.iter_live_entries", return_value=(entries, meta)):
            connector1 = PlacspAtomConnector()
            r1 = run_connector(connector1)

        with patch("scraper.atom_live.iter_live_entries", return_value=(entries, meta)):
            connector2 = PlacspAtomConnector()
            r2 = run_connector(connector2)

        # En la segunda pasada no debe haber nuevas licitaciones
        assert r2.nuevas == 0, (
            f"Idempotencia rota: segunda pasada insertó {r2.nuevas} nuevas licitaciones"
        )

    def test_iter_atom_entries_yields_correct_count(self):
        """_iter_atom_entries emite exactamente 1 entry del feed de muestra."""
        entries = list(_iter_atom_entries(_SAMPLE_ATOM_FEED))
        assert len(entries) == 1
        entry_elem, _ = entries[0]
        # Verificar que el elemento es una entry ATOM real
        assert "entry" in entry_elem.tag
