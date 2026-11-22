"""Tests para shared.geo."""

from __future__ import annotations


class TestNutsToCcaaShared:
    def test_unknown_returns_none(self):
        from shared.geo import nuts_to_ccaa

        assert nuts_to_ccaa("ES999") is None

    def test_nuts2_prefix_fallback(self):
        from shared.geo import nuts_to_ccaa

        assert nuts_to_ccaa("ES30") == "Madrid"

    def test_nuts2_prefix_andalucia(self):
        from shared.geo import nuts_to_ccaa

        assert nuts_to_ccaa("ES61") == "Andalucía"
