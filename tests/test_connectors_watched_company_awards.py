"""Contratos del carril PLACSP de adjudicaciones por empresa vigilada."""

from __future__ import annotations

import textwrap
from typing import Any
from unittest.mock import patch

from lxml import etree

from scraper.connectors.base import RawNotice, run_connector
from scraper.connectors.watched_company_awards import (
    ANALYSIS_UNIVERSE,
    INCLUSION_REASON,
    SOURCE_ID,
    PlacspWatchedCompanyAwardsBulkConnector,
    PlacspWatchedCompanyAwardsConnector,
)


def _entry(*, nif: str, contract_id: str = "WATCH-001") -> tuple[Any, str]:
    xml = textwrap.dedent(
        f"""\
        <feed xmlns="http://www.w3.org/2005/Atom"
              xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
              xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2"
              xmlns:cacext="urn:dgpe:names:draft:codice-place-ext:schema:xsd:CommonAggregateComponents-2">
          <entry>
            <id>https://contratacion.example/{contract_id}</id>
            <title>Servicio no tecnológico observado por empresa</title>
            <updated>2026-07-30T09:00:00Z</updated>
            <summary>Expediente de prueba</summary>
            <link href="https://contratacion.example/{contract_id}"/>
            <cacext:ContractFolderStatus>
              <cbc:ContractFolderID>{contract_id}</cbc:ContractFolderID>
              <cac:ProcurementProject>
                <cbc:Name>Servicio no tecnológico observado por empresa</cbc:Name>
              </cac:ProcurementProject>
              <cac:TenderResult>
                <cbc:AwardDate>2026-07-29</cbc:AwardDate>
                <cac:WinningParty>
                  <cac:PartyName><cbc:Name>Empresa Vigilada S.L.</cbc:Name></cac:PartyName>
                  <cac:PartyIdentification><cbc:ID>{nif}</cbc:ID></cac:PartyIdentification>
                </cac:WinningParty>
              </cac:TenderResult>
            </cacext:ContractFolderStatus>
          </entry>
        </feed>
        """
    ).encode()
    root = etree.fromstring(xml)
    entry = root.find("{http://www.w3.org/2005/Atom}entry")
    assert entry is not None
    return entry, "2026-07-30T09:00:00Z"


def test_parse_unfiltered_persists_non_technology_award_for_watched_nif() -> None:
    entry, updated = _entry(nif="B-12345678")
    connector = PlacspWatchedCompanyAwardsConnector({"B12345678"})

    parsed = connector.parse(RawNotice(natural_id="notice", payload=(entry, updated)))

    assert parsed is not None
    assert parsed.licitacion.id_externo == f"{SOURCE_ID}:WATCH-001"
    assert parsed.licitacion.fuente == SOURCE_ID
    assert parsed.licitacion.tecnologia is None
    assert parsed.licitacion.analysis_universe == ANALYSIS_UNIVERSE
    assert parsed.licitacion.inclusion_reason == INCLUSION_REASON
    assert parsed.adjudicaciones[0].licitacion_id == parsed.licitacion.id_externo
    assert parsed.adjudicaciones[0].nif == "B-12345678"


def test_parse_discards_award_without_watched_nif() -> None:
    entry, updated = _entry(nif="B99999999")
    connector = PlacspWatchedCompanyAwardsConnector({"B12345678"})

    assert connector.parse(RawNotice(natural_id="notice", payload=(entry, updated))) is None


def test_empty_watchlist_does_not_download_atom_feed() -> None:
    connector = PlacspWatchedCompanyAwardsConnector([])

    with patch("scraper.atom_live.iter_live_entries") as fetch_atom:
        assert list(connector.fetch(None)) == []

    fetch_atom.assert_not_called()


def test_runner_is_idempotent_and_uses_own_cursor(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    entry, updated = _entry(nif="B12345678")
    meta = {
        "newest_updated": updated,
        "etag": '"watched"',
        "last_modified": None,
        "pages_fetched": 1,
        "entries_seen": 1,
        "stopped_reason": "exhausted",
    }

    with patch("scraper.atom_live.iter_live_entries", return_value=([(entry, updated)], meta)):
        first = run_connector(PlacspWatchedCompanyAwardsConnector({"B12345678"}))
    with patch("scraper.atom_live.iter_live_entries", return_value=([(entry, updated)], meta)):
        second = run_connector(PlacspWatchedCompanyAwardsConnector({"B12345678"}))

    assert first.nuevas == 1
    assert second.nuevas == 0
    assert db_mod.get_cursor(SOURCE_ID)["last_seen_updated"] == updated
    assert db_mod.get_cursor("placsp") is None


def test_repository_lists_unique_nonempty_canonical_nifs(tmp_db: Any) -> None:
    db_mod, _ = tmp_db
    from db.repositories.watched_companies import WatchedCompanyRepository

    with db_mod.connect() as c:
        c.execute("INSERT INTO empresas (nif_canonico, nombre_canonico) VALUES (?, ?)", ("B12345678", "Uno"))
        c.execute("INSERT INTO empresas (nif_canonico, nombre_canonico) VALUES (?, ?)", (None, "Sin NIF"))
        first_id = c.execute("SELECT empresa_id FROM empresas WHERE nombre_canonico = 'Uno'").fetchone()[0]
        empty_id = c.execute("SELECT empresa_id FROM empresas WHERE nombre_canonico = 'Sin NIF'").fetchone()[0]
        c.execute("INSERT INTO watchlist_empresas (user_key, empresa_id) VALUES (?, ?)", ("u1", first_id))
        c.execute("INSERT INTO watchlist_empresas (user_key, empresa_id) VALUES (?, ?)", ("u2", first_id))
        c.execute("INSERT INTO watchlist_empresas (user_key, empresa_id) VALUES (?, ?)", ("u3", empty_id))

    assert WatchedCompanyRepository().list_canonical_nifs() == {"B12345678"}


def test_cli_exits_successfully_without_watched_nifs(monkeypatch: Any) -> None:
    from scraper.connectors import watched_company_awards

    monkeypatch.setattr("db.database.init_db", lambda: None)
    monkeypatch.setattr(
        "db.repositories.watched_companies.WatchedCompanyRepository.list_canonical_nifs",
        lambda self: set(),
    )
    with patch("scraper.connectors.base.run_connector") as runner:
        assert watched_company_awards.main([]) == 0
    runner.assert_not_called()


def test_bulk_connector_is_parameterized_and_has_no_cursor() -> None:
    connector = PlacspWatchedCompanyAwardsBulkConnector(2026, 7, {"B12345678"})

    assert connector.source_id == f"{SOURCE_ID}_bulk_202607"
    assert connector.new_cursor() is None
