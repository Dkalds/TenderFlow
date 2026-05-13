"""Template Plotly premium_dark construido desde los design tokens.

Premium refresh:
- Grid solo horizontal (más limpio).
- Líneas de eje más finas, casi invisibles.
- Tooltips con fondo oscuro sólido y borde 1px.
- Series con line.width 2.5 (líneas) y bargap más generoso.
- Tipografía Inter Tight.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

from dashboard.theme.tokens import TOKENS, Tokens

PLOTLY_TEMPLATE_NAME = "plotly_dark+premium_dark"

PLOTLY_CONFIG: dict[str, object] = {
    "displaylogo": False,
    "modeBarButtonsToRemove": [
        "lasso2d",
        "select2d",
        "autoScale2d",
        "hoverClosestCartesian",
        "hoverCompareCartesian",
        "toggleSpikelines",
    ],
    "displayModeBar": "hover",
    "responsive": True,
}


def build_plotly_template(t: Tokens = TOKENS) -> go.layout.Template:
    c = t.colors
    ty = t.type
    grid_color = "rgba(255,255,255,0.04)"
    axis_color = "rgba(255,255,255,0.05)"

    layout = go.Layout(
        font=dict(family=ty.family_plotly, color=c.text_plot_body, size=ty.size_plot_body),
        title=dict(
            font=dict(family=ty.family_plotly, size=14, color=c.text_card_title, weight=600),
            x=0.0,
            xanchor="left",
            pad=dict(t=4, b=10),
        ),
        margin=dict(t=44, r=18, b=44, l=58),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            showgrid=False,  # x sin grid → más limpio
            zeroline=False,
            linecolor=axis_color,
            linewidth=1,
            showline=False,
            tickfont=dict(size=ty.size_plot_axis, color=c.text_plot_axis),
            title=dict(font=dict(size=ty.size_plot_body, color=c.text_plot_body)),
            automargin=True,
            ticks="outside",
            tickcolor=axis_color,
            ticklen=4,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=grid_color,
            gridwidth=1,
            zeroline=False,
            linecolor=axis_color,
            linewidth=1,
            showline=False,
            tickfont=dict(size=ty.size_plot_axis, color=c.text_plot_axis),
            title=dict(font=dict(size=ty.size_plot_body, color=c.text_plot_body)),
            automargin=True,
        ),
        colorway=list(c.plotly_colorway),
        hoverlabel=dict(
            bgcolor=c.bg_hoverlabel,
            bordercolor=c.border_hoverlabel,
            font=dict(family=ty.family_plotly, size=ty.size_plot_body, color=c.text_card_title),
            namelength=-1,
            align="left",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=ty.size_plot_axis, color=c.text_plot_body),
            itemwidth=30,
        ),
        modebar=dict(
            bgcolor="rgba(0,0,0,0)",
            color=c.text_muted,
            activecolor=c.accent_primary,
        ),
        bargap=0.28,
        bargroupgap=0.06,
        separators=",.",
        # Transición global suave
        transition=dict(duration=350, easing="cubic-in-out"),
    )
    return go.layout.Template(layout=layout)


def register_plotly_template(t: Tokens = TOKENS) -> str:
    """Registra el template en pio.templates y devuelve el nombre completo."""
    pio.templates["premium_dark"] = build_plotly_template(t)
    return PLOTLY_TEMPLATE_NAME


def get_color_sequence(t: Tokens = TOKENS) -> list[str]:
    """Lista para `color_discrete_sequence=...` en px.*."""
    return list(t.colors.plotly_colorway)
