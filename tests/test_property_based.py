"""Property-based tests using Hypothesis.

Targets:
  - scraper.codice_parser.parse_summary
  - dashboard.utils.security.safe_url
  - dashboard.normalize.normalize_company
  - scraper.filters.matches_sap
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from dashboard.normalize import normalize_company
from dashboard.utils.security import safe_url
from scraper.codice_parser import parse_summary
from scraper.filters import matches_sap

# ── shared strategies ─────────────────────────────────────────────────────────

_text = st.text(min_size=0, max_size=200)
_text_or_none = st.one_of(st.none(), _text)
_non_str = st.one_of(st.integers(), st.floats(allow_nan=False), st.booleans(), st.binary())

_VALID_KEYS = {"id_externo", "organo_contratacion", "estado", "moneda", "importe"}


# ── parse_summary ─────────────────────────────────────────────────────────────


class TestParseSummaryProperties:
    @given(_text_or_none)
    def test_always_returns_dict(self, summary):
        """parse_summary never raises and always returns a dict."""
        result = parse_summary(summary)
        assert isinstance(result, dict)

    @given(_text_or_none)
    def test_keys_are_subset_of_expected(self, summary):
        """Output keys are always within the documented set."""
        result = parse_summary(summary)
        assert set(result.keys()) <= _VALID_KEYS

    @given(st.one_of(st.none(), st.just("")))
    def test_empty_or_none_returns_empty_dict(self, summary):
        """None and empty string always return {}."""
        assert parse_summary(summary) == {}

    @given(_text_or_none)
    def test_importe_is_float_when_present(self, summary):
        """When 'importe' key is present it must be a float."""
        result = parse_summary(summary)
        if "importe" in result:
            assert isinstance(result["importe"], float)

    @given(_text_or_none)
    def test_moneda_is_nonempty_string_when_present(self, summary):
        """When 'moneda' key is present it must be a non-empty string."""
        result = parse_summary(summary)
        if "moneda" in result:
            assert isinstance(result["moneda"], str)
            assert result["moneda"]  # non-empty

    @given(
        id_=st.text(
            min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"))
        ),
        organo=st.text(
            min_size=1, max_size=50, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Zs"))
        ),
        importe=st.decimals(
            min_value=0, max_value=1_000_000_000, places=2, allow_nan=False, allow_infinity=False
        ),
        estado=st.sampled_from(["PUB", "ADJ", "RES", "ANU", "EV"]),
    )
    def test_well_formed_summary_parsed_correctly(self, id_, organo, importe, estado):
        """A correctly formatted summary string produces the expected keys."""
        importe_str = str(importe).replace("E+", "e+")  # avoid scientific notation issues
        summary = (
            f"Id licitación: {id_}; "
            f"Órgano de Contratación: {organo}; "
            f"Importe: {importe_str} EUR; "
            f"Estado: {estado}"
        )
        result = parse_summary(summary)
        assert result.get("id_externo") == id_.strip()
        assert result.get("organo_contratacion") == organo.strip()
        assert result.get("estado") == estado
        assert result.get("moneda") == "EUR"


# ── safe_url ──────────────────────────────────────────────────────────────────


class TestSafeUrlProperties:
    @given(_text_or_none)
    def test_returns_none_or_string(self, url):
        """safe_url always returns None or str, never raises."""
        result = safe_url(url)
        assert result is None or isinstance(result, str)

    @given(_text_or_none)
    def test_non_http_returns_none(self, url):
        """URLs that don't start with http:// or https:// are rejected."""
        if url is not None and not url.strip().lower().startswith(("http://", "https://")):
            assert safe_url(url) is None

    @given(st.text(min_size=1, max_size=100).map(lambda s: "http://" + s))
    def test_http_url_accepted(self, url):
        """http:// URLs are always accepted and returned stripped."""
        result = safe_url(url)
        assert result == url.strip()

    @given(st.text(min_size=1, max_size=100).map(lambda s: "https://" + s))
    def test_https_url_accepted(self, url):
        """https:// URLs are always accepted and returned stripped."""
        result = safe_url(url)
        assert result == url.strip()

    @given(st.text(min_size=1, max_size=100).map(lambda s: "HTTPS://" + s))
    def test_https_case_insensitive(self, url):
        """Scheme check is case-insensitive."""
        result = safe_url(url)
        assert result == url.strip()

    @given(
        st.sampled_from(
            ["javascript:", "data:", "ftp://", "file://", "vbscript:", "mailto:"]
        ).flatmap(lambda prefix: st.text(min_size=0, max_size=80).map(lambda s: prefix + s))
    )
    def test_dangerous_schemes_rejected(self, url):
        """Known dangerous/non-http schemes are always rejected."""
        assert safe_url(url) is None

    @given(_non_str)
    def test_non_string_returns_none(self, value):
        """Non-string inputs always return None without raising."""
        assert safe_url(value) is None  # type: ignore[arg-type]

    @given(st.just(None))
    def test_none_returns_none(self, url):
        assert safe_url(url) is None


# ── normalize_company ─────────────────────────────────────────────────────────


class TestNormalizeCompanyProperties:
    @given(_text_or_none)
    def test_returns_none_or_nonempty_string(self, name):
        """normalize_company never raises and returns None or non-empty str."""
        result = normalize_company(name)
        assert result is None or (isinstance(result, str) and result)

    @given(_text_or_none)
    def test_result_has_no_leading_trailing_whitespace(self, name):
        """The result must not have leading or trailing whitespace."""
        result = normalize_company(name)
        if result is not None:
            assert result == result.strip()

    @given(_text_or_none)
    def test_result_is_uppercase(self, name):
        """The result must be fully uppercase (accents already stripped)."""
        result = normalize_company(name)
        if result is not None:
            assert result == result.upper()

    @given(_text_or_none)
    @settings(max_examples=200)
    def test_idempotent(self, name):
        """normalize_company(normalize_company(x)) == normalize_company(x)."""
        first = normalize_company(name)
        second = normalize_company(first)
        assert first == second

    @given(st.one_of(st.none(), st.just(""), st.just("   ")))
    def test_empty_or_none_returns_none(self, name):
        """None, empty string, and whitespace-only string return None."""
        assert normalize_company(name) is None

    @given(_non_str)
    def test_non_string_returns_none(self, value):
        """Non-string inputs return None without raising."""
        assert normalize_company(value) is None  # type: ignore[arg-type]

    @given(
        st.text(
            min_size=1, max_size=60, alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Zs"))
        )
    )
    def test_result_has_no_extra_internal_whitespace(self, name):
        """Result never has consecutive internal spaces."""
        result = normalize_company(name)
        if result is not None:
            assert "  " not in result


# ── matches_sap ───────────────────────────────────────────────────────────────


class TestMatchesSapProperties:
    @given(_text_or_none)
    def test_returns_bool_and_list(self, text):
        """matches_sap always returns (bool, list) without raising."""
        result = matches_sap(text)
        assert isinstance(result, tuple) and len(result) == 2
        matched, found = result
        assert isinstance(matched, bool)
        assert isinstance(found, list)

    @given(st.lists(_text_or_none, min_size=0, max_size=5))
    def test_variadic_never_raises(self, texts):
        """matches_sap accepts any number of str|None args without raising."""
        result = matches_sap(*texts)
        assert isinstance(result, tuple)

    @given(_text_or_none)
    def test_found_list_is_sorted(self, text):
        """The returned keyword list is always sorted."""
        _, found = matches_sap(text)
        assert found == sorted(found)

    @given(_text_or_none)
    def test_found_items_are_lowercase(self, text):
        """Each keyword in the found list is lowercase."""
        _, found = matches_sap(text)
        for kw in found:
            assert kw == kw.lower()

    @given(_text_or_none)
    def test_bool_consistent_with_list(self, text):
        """The bool return is True iff the found list is non-empty."""
        matched, found = matches_sap(text)
        assert matched == bool(found)

    @given(st.one_of(st.none(), st.just("")))
    def test_empty_or_none_returns_false_empty(self, text):
        """None and empty string always return (False, [])."""
        assert matches_sap(text) == (False, [])

    @given(st.just("SAP ERP"))
    def test_known_keyword_matches(self, text):
        """'SAP ERP' always triggers a match."""
        matched, found = matches_sap(text)
        assert matched is True
        assert "sap" in found
