"""Tests para dashboard/utils/chart_helpers.py."""

from __future__ import annotations

from unittest.mock import MagicMock

from dashboard.utils.chart_helpers import apply_chart_defaults, fmt_hover_eur


class TestFmtHoverEur:
    def test_below_1000(self):
        assert fmt_hover_eur(500.0) == "500 €"

    def test_exactly_1000(self):
        assert fmt_hover_eur(1000.0) == "1K €"

    def test_thousands(self):
        assert fmt_hover_eur(25_000.0) == "25K €"

    def test_millions(self):
        assert fmt_hover_eur(2_500_000.0) == "2.5M €"

    def test_exactly_1_million(self):
        assert fmt_hover_eur(1_000_000.0) == "1.0M €"

    def test_zero(self):
        assert fmt_hover_eur(0.0) == "0 €"


class TestApplyChartDefaults:
    def test_calls_update_layout(self):
        fig = MagicMock()
        apply_chart_defaults(fig)
        assert fig.update_layout.called

    def test_calls_update_yaxes(self):
        fig = MagicMock()
        apply_chart_defaults(fig)
        fig.update_yaxes.assert_called_once_with(separatethousands=True)

    def test_calls_update_xaxes(self):
        fig = MagicMock()
        apply_chart_defaults(fig)
        fig.update_xaxes.assert_called_once_with(separatethousands=True)

    def test_custom_height_passed(self):
        fig = MagicMock()
        apply_chart_defaults(fig, height=500)
        calls = fig.update_layout.call_args_list
        # First call should have height=500
        first_call_kwargs = calls[0][1]
        assert first_call_kwargs.get("height") == 500
