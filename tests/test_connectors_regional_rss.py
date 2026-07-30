"""Parsing contracts for the official Galicia and Euskadi regional RSS feeds."""

from __future__ import annotations

from typing import Any

from scraper.connectors.base import ConnectorRunResult, RawNotice
from scraper.connectors.euskadi import EuskadiRssConnector
from scraper.connectors.galicia import GaliciaRssConnector


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _Session:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        return _Response(self.content)


_GALICIA_RSS = b'''<?xml version="1.0" encoding="ISO-8859-1"?>
<rss version="2.0"><channel><item>
<title><![CDATA[AXI-2026-0028: Servizo de mantemento SAP - ID: 828765]]></title>
<link>https://www.contratosdegalicia.gal/licitacion?N=828765</link>
<description><![CDATA[<p><b>Estado:</b> En curso</p><p><b>&Oacute;rgano de contrataci&oacute;n:</b> Axencia Galega</p><p><b>Tipo de contrato:</b> Servizos</p><p><b>Importe:</b> 2.364.210,48 &euro;</p><p><b>Data de publicaci&oacute;n na plataforma:</b> 29-07-2026 07:53</p><p><b>Data e hora l&iacute;mite de presentaci&oacute;n de ofertas:</b> 07-09-2026 23:59</p>]]></description>
<guid>https://www.contratosdegalicia.gal/licitacion?N=828765</guid><pubDate>29-07-2026 07:53</pubDate>
</item></channel></rss>'''


def test_galicia_rss_fetches_and_parses_an_official_shape() -> None:
    session = _Session(_GALICIA_RSS)
    connector = GaliciaRssConnector(session=session)

    notices = list(connector.fetch(None))
    parsed = connector.parse(notices[0])

    assert session.calls[0][0] == connector.feed_url
    assert notices[0].natural_id == "828765"
    assert parsed is not None
    assert parsed.licitacion.id_externo == "galicia_rss:828765"
    assert parsed.licitacion.ccaa == "Galicia"
    assert parsed.licitacion.importe == 2364210.48
    assert parsed.licitacion.fecha_limite == "2026-09-07T23:59:00+00:00"
    assert connector.new_cursor() == {"last_seen_updated": "2026-07-29T07:53:00+00:00"}


def test_euskadi_uses_a_namespaced_id_and_discards_non_technology_notice() -> None:
    connector = EuskadiRssConnector()
    parsed = connector.parse(RawNotice("100", {"title": "Anuncio Oracle cloud - ID: 100", "link": "https://www.euskadi.eus/x?N=100", "description": "Estado: abierto Importe: 10.000,00 €", "published": "2026-07-29T08:00:00+00:00"}))
    ignored = connector.parse(RawNotice("101", {"title": "Obras en parque", "link": "https://www.euskadi.eus/x?N=101", "description": "Importe: 10.000,00 €", "published": "2026-07-29T08:00:00+00:00"}))

    assert parsed is not None
    assert parsed.licitacion.id_externo == "euskadi_rss:100"
    assert parsed.licitacion.ccaa == "País Vasco"
    assert ignored is None


def test_galicia_cli_initializes_db_and_returns_connector_status(monkeypatch: Any) -> None:
    monkeypatch.setattr("db.database.init_db", lambda: None)
    monkeypatch.setattr(
        "scraper.connectors.base.run_connector",
        lambda connector: ConnectorRunResult(source_id=connector.source_id),
    )

    assert GaliciaRssConnector.source_id == "galicia_rss"
    from scraper.connectors.galicia import main

    assert main([]) == 0


def test_euskadi_cli_returns_nonzero_when_connector_reports_errors(monkeypatch: Any) -> None:
    monkeypatch.setattr("db.database.init_db", lambda: None)
    monkeypatch.setattr(
        "scraper.connectors.base.run_connector",
        lambda connector: ConnectorRunResult(source_id=connector.source_id, errores=1),
    )

    from scraper.connectors.euskadi import main

    assert main([]) == 1
