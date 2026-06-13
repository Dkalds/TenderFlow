"""Tests para shared.geo."""

from __future__ import annotations


class TestNutsToCcaaShared:
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

        assert nuts_to_ccaa("ES30") == "Madrid"

    def test_nuts2_prefix_andalucia(self):
        from shared.geo import nuts_to_ccaa

        assert nuts_to_ccaa("ES61") == "Andalucía"
