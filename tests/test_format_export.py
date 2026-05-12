"""Tests para dashboard/utils/format.py, dashboard/utils/export.py y shared/geo.py."""

from __future__ import annotations

import pandas as pd

from dashboard.utils.format import fmt_eur, highlight_match


class TestFmtEurFormat:
    """Tests para la función fmt_eur de format.py."""

    def test_none_returns_dash(self):
        assert fmt_eur(None) == "—"

    def test_nan_returns_dash(self):
        assert fmt_eur(float("nan")) == "—"

    def test_small_amount(self):
        assert fmt_eur(500) == "500 €"

    def test_thousands(self):
        assert fmt_eur(5000) == "5.0 k€"

    def test_millions(self):
        result = fmt_eur(2_000_000)
        assert "M€" in result

    def test_billions(self):
        result = fmt_eur(3_000_000_000)
        assert "B€" in result

    def test_negative_millions(self):
        result = fmt_eur(-2_000_000)
        assert "M€" in result

    def test_zero(self):
        assert fmt_eur(0) == "0 €"


class TestHighlightMatch:
    def test_empty_query_returns_escaped(self):
        result = highlight_match("hola mundo", "")
        assert result == "hola mundo"

    def test_whitespace_query_returns_escaped(self):
        result = highlight_match("hola mundo", "   ")
        assert result == "hola mundo"

    def test_highlights_match(self):
        result = highlight_match("SAP system", "SAP")
        assert '<mark class="search-hl">SAP</mark>' in result

    def test_case_insensitive(self):
        result = highlight_match("SAP system", "sap")
        assert "mark" in result

    def test_single_char_token_not_highlighted(self):
        result = highlight_match("a SAP system", "a")
        assert "mark" not in result

    def test_escapes_html_in_text(self):
        result = highlight_match("<script>alert(1)</script>", "")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_multi_token_query(self):
        result = highlight_match("SAP S4HANA system", "SAP S4HANA")
        assert result.count("mark") >= 2


class TestKpisSnapshotCsv:
    def test_returns_bytes(self):
        from dashboard.utils.export import kpis_snapshot_csv

        result = kpis_snapshot_csv({"Total": "100 €"})
        assert isinstance(result, bytes)

    def test_has_bom(self):
        from dashboard.utils.export import kpis_snapshot_csv

        result = kpis_snapshot_csv({"Total": "100 €"})
        assert result.startswith(b"\xef\xbb\xbf")

    def test_contains_kpi_label(self):
        from dashboard.utils.export import kpis_snapshot_csv

        result = kpis_snapshot_csv({"Licitaciones": "42"})
        assert b"Licitaciones" in result

    def test_custom_titulo(self):
        from dashboard.utils.export import kpis_snapshot_csv

        result = kpis_snapshot_csv({}, titulo="Mi Reporte")
        assert b"Mi Reporte" in result

    def test_empty_kpis(self):
        from dashboard.utils.export import kpis_snapshot_csv

        result = kpis_snapshot_csv({})
        assert isinstance(result, bytes)
        assert len(result) > 0


class TestNutsToCcaaShared:
    """Tests para la función nuts_to_ccaa de shared/geo.py."""

    def test_exact_nuts3(self):
        from shared.geo import nuts_to_ccaa
        assert nuts_to_ccaa("ES300") == "Madrid"

    def test_case_insensitive(self):
        from shared.geo import nuts_to_ccaa
        assert nuts_to_ccaa("es300") == "Madrid"

    def test_none_returns_none(self):
        from shared.geo import nuts_to_ccaa
        assert nuts_to_ccaa(None) is None

    def test_empty_returns_none(self):
        from shared.geo import nuts_to_ccaa
        assert nuts_to_ccaa("") is None

    def test_unknown_returns_none(self):
        from shared.geo import nuts_to_ccaa
        assert nuts_to_ccaa("ES999") is None

    def test_nuts2_prefix_fallback(self):
        from shared.geo import nuts_to_ccaa
        # ES30 is NUTS2 for Madrid (ES300)
        result = nuts_to_ccaa("ES30")
        assert result == "Madrid"

    def test_nuts2_prefix_andalucia(self):
        from shared.geo import nuts_to_ccaa
        result = nuts_to_ccaa("ES61")
        assert result == "Andalucía"


class TestSafeUrlSecurity:
    """Tests para safe_url de dashboard/utils/security.py."""

    def test_http_accepted(self):
        from dashboard.utils.security import safe_url
        assert safe_url("http://example.com") == "http://example.com"

    def test_https_accepted(self):
        from dashboard.utils.security import safe_url
        assert safe_url("https://example.com") == "https://example.com"

    def test_javascript_rejected(self):
        from dashboard.utils.security import safe_url
        assert safe_url("javascript:alert(1)") is None

    def test_data_uri_rejected(self):
        from dashboard.utils.security import safe_url
        assert safe_url("data:text/html,<h1>hi</h1>") is None

    def test_none_returns_none(self):
        from dashboard.utils.security import safe_url
        assert safe_url(None) is None

    def test_non_string_returns_none(self):
        from dashboard.utils.security import safe_url
        assert safe_url(123) is None  # type: ignore[arg-type]

    def test_strips_whitespace(self):
        from dashboard.utils.security import safe_url
        assert safe_url("  https://example.com  ") == "https://example.com"
