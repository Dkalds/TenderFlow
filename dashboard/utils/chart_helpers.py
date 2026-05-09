"""Utilidades compartidas para gráficos Plotly."""

from __future__ import annotations

from typing import Any


def fmt_hover_eur(val: float) -> str:
    """Format euro values for hover tooltips."""
    if val >= 1_000_000:
        return f"{val / 1_000_000:,.1f}M €"
    if val >= 1_000:
        return f"{val / 1_000:,.0f}K €"
    return f"{val:,.0f} €"


def apply_chart_defaults(fig: Any, height: int = 380) -> None:
    """Apply consistent defaults to any Plotly figure."""
    fig.update_layout(
        height=height,
        margin=dict(t=20, b=10, l=10, r=10),
    )
    # Improve hover experience
    fig.update_layout(
        hovermode="closest",
        hoverdistance=30,
    )
    # Consistent number formatting on axes
    fig.update_yaxes(separatethousands=True)
    fig.update_xaxes(separatethousands=True)
