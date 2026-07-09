"""Tests para scraper/atom_live.py — cliente ATOM en vivo."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scraper.atom_live import (
    FetchResult,
    _entry_updated,
    _parse_feed_links,
    fetch_atom_page,
    iter_live_entries,
)

# ─── Fixtures XML ─────────────────────────────────────────────────────────────

_ATOM_PAGE_1 = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>PLACSP Feed</title>
  <link rel="next" href="https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom?page=2"/>
  <entry>
    <id>urn:uuid:entry-001</id>
    <updated>2026-05-01T10:00:00Z</updated>
    <title>Licitacion SAP S/4HANA</title>
    <summary>Servicio SAP S/4HANA</summary>
  </entry>
  <entry>
    <id>urn:uuid:entry-002</id>
    <updated>2026-05-01T09:00:00Z</updated>
    <title>Licitacion SAP BW</title>
    <summary>Consultoria SAP BW</summary>
  </entry>
</feed>
"""

_ATOM_PAGE_2 = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>PLACSP Feed</title>
  <entry>
    <id>urn:uuid:entry-003</id>
    <updated>2026-05-01T08:00:00Z</updated>
    <title>Licitacion SAP Fiori</title>
    <summary>Desarrollo SAP Fiori</summary>
  </entry>
  <entry>
    <id>urn:uuid:entry-004</id>
    <updated>2026-04-30T15:00:00Z</updated>
    <title>Licitacion SAP MM</title>
    <summary>Implantacion SAP MM</summary>
  </entry>
</feed>
"""

# ─── Helpers ──────────────────────────────────────────────────────────────────


class TestParseLinks:
    def test_extracts_next(self):
        from lxml import etree

        root = etree.fromstring(_ATOM_PAGE_1)
        assert _parse_feed_links(root) == (
            "https://contrataciondelsectorpublico.gob.es/sindicacion/"
            "sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom?page=2"
        )

    def test_no_next(self):
        from lxml import etree

        root = etree.fromstring(_ATOM_PAGE_2)
        assert _parse_feed_links(root) is None

    def test_accepts_contrataciondelestado_domain(self):
        """PLACE también sirve paginación bajo el dominio histórico."""
        from lxml import etree

        xml = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link rel="next" href="https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3_20260708_203728.atom"/>
</feed>"""
        root = etree.fromstring(xml)
        assert _parse_feed_links(root) == (
            "https://contrataciondelestado.es/sindicacion/sindicacion_643/"
            "licitacionesPerfilesContratanteCompleto3_20260708_203728.atom"
        )

    def test_rejects_external_domain(self):
        """SSRF protection: rechaza URLs de dominios externos."""
        from lxml import etree

        xml = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link rel="next" href="https://evil.example.com/steal?data=1"/>
</feed>"""
        root = etree.fromstring(xml)
        assert _parse_feed_links(root) is None

    def test_rejects_file_scheme(self):
        """SSRF protection: rechaza esquemas file://."""
        from lxml import etree

        xml = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <link rel="next" href="file:///etc/passwd"/>
</feed>"""
        root = etree.fromstring(xml)
        assert _parse_feed_links(root) is None


class TestEntryUpdated:
    def test_extracts_updated(self):
        from lxml import etree

        root = etree.fromstring(_ATOM_PAGE_1)
        ns = "http://www.w3.org/2005/Atom"
        entry = root.find(f"{{{ns}}}entry")
        assert _entry_updated(entry) == "2026-05-01T10:00:00Z"


# ─── fetch_atom_page ─────────────────────────────────────────────────────────


class TestFetchAtomPage:
    @patch("scraper.atom_live.requests.get")
    def test_normal_200(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = _ATOM_PAGE_1
        resp.headers = {"ETag": '"abc"', "Last-Modified": "Thu, 01 May 2026 10:00:00 GMT"}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = fetch_atom_page("https://example.com/feed")
        assert result.status_code == 200
        assert result.content == _ATOM_PAGE_1
        assert result.etag == '"abc"'

    @patch("scraper.atom_live.requests.get")
    def test_304_not_modified(self, mock_get):
        resp = MagicMock()
        resp.status_code = 304
        resp.content = b""
        resp.headers = {}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        result = fetch_atom_page("https://example.com/feed", etag='"old"')
        assert result.status_code == 304
        assert result.content is None

    @patch("scraper.atom_live.requests.get")
    def test_sends_conditional_headers(self, mock_get):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = _ATOM_PAGE_1
        resp.headers = {}
        resp.raise_for_status = MagicMock()
        mock_get.return_value = resp

        fetch_atom_page(
            "https://example.com/feed",
            etag='"my-etag"',
            last_modified="Thu, 01 May 2026",
        )
        call_kwargs = mock_get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["If-None-Match"] == '"my-etag"'
        assert headers["If-Modified-Since"] == "Thu, 01 May 2026"


# ─── iter_live_entries ────────────────────────────────────────────────────────


class TestIterLiveEntries:
    def _mock_fetch(self, pages: dict[str, bytes]):
        """Returns a side_effect function that maps URLs to FetchResults."""

        def _fetch(url, **kwargs):
            content = pages.get(url)
            if content is None:
                raise ValueError(f"Unexpected URL: {url}")
            return FetchResult(content=content, status_code=200)

        return _fetch

    @patch("scraper.atom_live.fetch_atom_page")
    @patch("scraper.atom_live.time.sleep")  # skip delays
    def test_bootstrap_only_first_page(self, mock_sleep, mock_fetch):
        """Sin cursor (bootstrap) solo procesa la primera página."""
        mock_fetch.return_value = FetchResult(content=_ATOM_PAGE_1, status_code=200)

        entries, meta = iter_live_entries(last_seen_updated=None, start_url="https://x.com/feed")

        assert meta["pages_fetched"] == 1
        assert meta["stopped_reason"] == "bootstrap"
        assert len(entries) == 2

    @patch("scraper.atom_live.fetch_atom_page")
    @patch("scraper.atom_live.time.sleep")
    def test_cursor_stops_at_seen_updated(self, mock_sleep, mock_fetch):
        """Con cursor, corta cuando entry.updated <= cursor."""
        # Página 1 tiene entries con updated 10:00 y 09:00
        mock_fetch.return_value = FetchResult(content=_ATOM_PAGE_1, status_code=200)

        entries, meta = iter_live_entries(
            last_seen_updated="2026-05-01T09:30:00Z",
            start_url="https://x.com/feed",
        )

        # Solo la entry con 10:00 debería pasar (> 09:30)
        assert len(entries) == 1
        assert entries[0][1] == "2026-05-01T10:00:00Z"
        assert meta["stopped_reason"] == "cursor_reached"

    @patch("scraper.atom_live.fetch_atom_page")
    @patch("scraper.atom_live.time.sleep")
    def test_paginates_with_next_link(self, mock_sleep, mock_fetch):
        """Con cursor viejo, pagina múltiples páginas."""
        page2_url = (
            "https://contrataciondelsectorpublico.gob.es/sindicacion/"
            "sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom?page=2"
        )
        pages = {
            "https://x.com/feed": FetchResult(content=_ATOM_PAGE_1, status_code=200),
            page2_url: FetchResult(content=_ATOM_PAGE_2, status_code=200),
        }
        mock_fetch.side_effect = lambda url, **kw: pages[url]

        entries, meta = iter_live_entries(
            last_seen_updated="2026-04-30T00:00:00Z",
            start_url="https://x.com/feed",
        )

        assert meta["pages_fetched"] == 2
        assert len(entries) == 4  # 2 per page

    @patch("scraper.atom_live.fetch_atom_page")
    @patch("scraper.atom_live.time.sleep")
    def test_304_stops_immediately(self, mock_sleep, mock_fetch):
        """304 Not Modified = nada nuevo."""
        mock_fetch.return_value = FetchResult(content=None, status_code=304)

        entries, meta = iter_live_entries(
            last_seen_updated="2026-05-01T09:00:00Z",
            start_url="https://x.com/feed",
        )

        assert len(entries) == 0
        assert meta["stopped_reason"] == "not_modified"

    @patch("scraper.atom_live.fetch_atom_page")
    @patch("scraper.atom_live.time.sleep")
    def test_max_pages_respected(self, mock_sleep, mock_fetch):
        """No sobrepasa max_pages."""
        mock_fetch.return_value = FetchResult(content=_ATOM_PAGE_1, status_code=200)

        _entries, meta = iter_live_entries(
            last_seen_updated="2026-01-01T00:00:00Z",
            start_url="https://x.com/feed",
            max_pages=1,
        )

        assert meta["pages_fetched"] == 1

    @patch("scraper.atom_live.fetch_atom_page")
    @patch("scraper.atom_live.time.sleep")
    def test_newest_updated_tracked(self, mock_sleep, mock_fetch):
        """meta['newest_updated'] refleja el timestamp más reciente."""
        mock_fetch.return_value = FetchResult(content=_ATOM_PAGE_1, status_code=200)

        _, meta = iter_live_entries(
            last_seen_updated="2026-04-30T00:00:00Z",
            start_url="https://x.com/feed",
            max_pages=1,
        )

        assert meta["newest_updated"] == "2026-05-01T10:00:00Z"
