"""Template Plotly premium_dark construido desde los design tokens.

Premium refresh v2:
- Grid solo horizontal (más limpio).
- Líneas de eje más finas, casi invisibles.
- Tooltips con fondo oscuro sólido y borde 1px.
- Series con line.width 2.5 (líneas) y bargap más generoso.
- Tipografía Geist (con Inter Tight como fallback).
- hovermode="x unified" para hover unificado en series temporales.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from dashboard.theme.tokens import TOKENS, Tokens

PLOTLY_TEMPLATE_NAME = "plotly_dark+premium_dark"
PLOTLY_TEMPLATE_NAME_LIGHT = "plotly+premium_light"

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
    grid_color = "rgba(255,255,255,0.045)"
    axis_color = "rgba(255,255,255,0.04)"

    layout = go.Layout(
        font=dict(family=ty.family_plotly, color=c.text_plot_body, size=ty.size_plot_body),
        title=dict(
            font=dict(family=ty.family_plotly, size=14, color=c.text_card_title, weight=600),
            x=0.0,
            xanchor="left",
            pad=dict(t=4, b=8),
        ),
        margin=dict(t=24, r=24, b=32, l=48),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            linecolor=axis_color,
            linewidth=1,
            showline=False,
            tickfont=dict(size=ty.size_plot_axis, color=c.text_plot_axis),
            title=dict(font=dict(size=ty.size_plot_body, color=c.text_plot_body)),
            automargin=True,
            ticks="outside",
            tickcolor="rgba(0,0,0,0)",
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


@st.cache_resource
def register_plotly_template(t: Tokens = TOKENS) -> str:
    """Registra el template en pio.templates y devuelve el nombre completo.

    Decorado con ``@st.cache_resource`` para que el registro (costoso para
    Plotly interno) sólo ocurra una vez por proceso, no en cada rerun.
    """
    pio.templates["premium_dark"] = build_plotly_template(t)
    pio.templates["premium_light"] = build_plotly_template_light(t)
    return PLOTLY_TEMPLATE_NAME


def build_plotly_template_light(t: Tokens = TOKENS) -> go.layout.Template:
    """Template Plotly para el tema claro (premium_light)."""
    lc = t.light
    ty = t.type
    grid_color = lc.border_plot
    axis_color = lc.border_subtle

    layout = go.Layout(
        font=dict(family=ty.family_plotly, color=lc.text_plot_body, size=ty.size_plot_body),
        title=dict(
            font=dict(family=ty.family_plotly, size=14, color=lc.text_card_title, weight=600),
            x=0.0,
            xanchor="left",
            pad=dict(t=4, b=8),
        ),
        margin=dict(t=24, r=24, b=32, l=48),
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        hovermode="x unified",
        xaxis=dict(
            showgrid=False,
            zeroline=False,
            linecolor=axis_color,
            linewidth=1,
            showline=False,
            tickfont=dict(size=ty.size_plot_axis, color=lc.text_plot_axis),
            title=dict(font=dict(size=ty.size_plot_body, color=lc.text_plot_body)),
            automargin=True,
            ticks="outside",
            tickcolor="rgba(0,0,0,0)",
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
            tickfont=dict(size=ty.size_plot_axis, color=lc.text_plot_axis),
            title=dict(font=dict(size=ty.size_plot_body, color=lc.text_plot_body)),
            automargin=True,
        ),
        colorway=list(t.colors.plotly_colorway),
        hoverlabel=dict(
            bgcolor=lc.bg_hoverlabel,
            bordercolor=lc.border_hoverlabel,
            font=dict(family=ty.family_plotly, size=ty.size_plot_body, color=lc.text_card_title),
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
            font=dict(size=ty.size_plot_axis, color=lc.text_plot_body),
            itemwidth=30,
        ),
        modebar=dict(
            bgcolor="rgba(0,0,0,0)",
            color=lc.text_muted,
            activecolor=lc.accent_primary,
        ),
        bargap=0.28,
        bargroupgap=0.06,
        separators=",.",
        transition=dict(duration=350, easing="cubic-in-out"),
    )
    return go.layout.Template(layout=layout)


def current_plotly_template() -> str:
    """Devuelve el nombre del template activo según el tema de la sesión."""
    try:
        import streamlit as st
        if st.session_state.get("ui_light_mode", False):
            return PLOTLY_TEMPLATE_NAME_LIGHT
    except Exception:
        pass
    return PLOTLY_TEMPLATE_NAME


def get_color_sequence(t: Tokens = TOKENS) -> list[str]:
    """Lista para `color_discrete_sequence=...` en px.*."""
    return list(t.colors.plotly_colorway)


def apply_premium_line_style(fig: go.Figure, width: float = 2.5) -> go.Figure:
    """Aplica estilo premium a todas las trazas de línea de una figura.

    - Line width uniforme.
    - connectgaps=True para series con huecos.
    - Marcadores pequeños solo en el último punto (hover-friendly).

    Returns:
        La misma figura mutada (para uso en cadena: ``fig = apply_premium_line_style(fig)``).
    """
    for trace in fig.data:
        if isinstance(trace, go.Scatter):
            trace.update(
                line=dict(width=width, shape="spline", smoothing=0.6),
                connectgaps=True,
            )
    return fig
