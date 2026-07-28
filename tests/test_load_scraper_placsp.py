"""Load tests for scraper PLACSP: XML parsing + bulk upsert performance."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_simple_atom(n: int) -> bytes:
    """Minimal ATOM-like XML with n entries for parsing benchmarks."""
    entries = []
    for i in range(n):
        entries.append(
            f"  <entry><id>id-{i}</id><title>Test {i}</title>"
            f"<updated>2026-01-15T10:00:00Z</updated></entry>"
        )
    body = "\n".join(entries)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"{body}\n"
        "</feed>"
    ).encode()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.load
class TestXmlParsingThroughput:
    """Benchmark: parse N entries from synthetic ATOM XML."""

    @pytest.mark.parametrize("n", [100, 500, 1000])
    def test_parse_throughput(self, n: int) -> None:
        xml_bytes = _build_simple_atom(n)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        root = ET.fromstring(xml_bytes)  # noqa: S314 - synthetic trusted XML built in-test
        entries = root.findall("atom:entry", ns)
        assert len(entries) == n

        t0 = time.perf_counter()
        parsed = 0
        for entry in entries:
            uid_el = entry.find("atom:id", ns)
            title_el = entry.find("atom:title", ns)
            if uid_el is not None and title_el is not None:
                parsed += 1
        elapsed = time.perf_counter() - t0

        assert parsed == n
        throughput = n / elapsed if elapsed > 0 else float("inf")
        assert throughput > 10_000, f"Parsing too slow: {throughput:.0f} entries/sec"


@pytest.mark.load
class TestBulkUpsertPerformance:
    """Benchmark: bulk upsert of synthetic licitaciones."""

    @pytest.mark.parametrize("n", [100, 500])
    def test_upsert_throughput(self, n: int, tmp_db) -> None:
        from db.database import Licitacion
        from db.upsert import upsert_licitaciones

        lics = [
            Licitacion(
                id_externo=f"BULK-{i:05d}",
                titulo=f"Bulk test {i}",
                organo_contratacion=f"Organo {i}",
                estado="En plazo",
                fecha_publicacion="2026-01-15",
                importe=100000.0 + i,
                cpv="72000000",
                url=f"https://example.com/{i}",
            )
            for i in range(n)
        ]

        t0 = time.perf_counter()
        inserted, updated = upsert_licitaciones(lics)
        elapsed = time.perf_counter() - t0

        assert inserted + updated == n
        throughput = n / elapsed if elapsed > 0 else float("inf")
        assert throughput > 200, f"Upsert too slow: {throughput:.0f} lic/s"
