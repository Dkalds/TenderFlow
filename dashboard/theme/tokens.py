"""Design tokens — única fuente de verdad del tema corporativo.

Premium refresh:
- Paleta dark más neutra (estilo Vercel/Linear), bg casi negro `#0A0A0B`.
- Surfaces sólidas con leve gradient interior (sin glass-morphism agresivo).
- Tipografía: Inter Tight como display + tabular-nums para KPIs.
- Bordes 1px sutiles (rgba 6-8% blanco) para look enterprise.
- Light mode tokens paralelos (`LIGHT_TOKENS`) — mismo schema, valores claros.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Colors:
    # Base surfaces (dark mode default — paleta Vercel-like)
    bg_base: str = "#0A0A0B"  # casi negro, neutro
    bg_sidebar_top: str = "#0C0C0E"
    bg_sidebar_bottom: str = "#0A0A0B"
    bg_elev_1: str = "#111114"  # surface 1 (cards)
    bg_elev_2: str = "#16161A"  # surface 2 (cards activas / tablas)
    bg_hoverlabel: str = "#1A1A1F"

    # Borders (más sutiles, 6-8%)
    border_subtle: str = "rgba(255,255,255,0.06)"
    border_card: str = "rgba(255,255,255,0.07)"
    border_hover: str = "rgba(255,255,255,0.14)"
    border_plot: str = "rgba(255,255,255,0.06)"
    border_hoverlabel: str = "rgba(255,255,255,0.10)"

    # Text
    text_primary: str = "#F4F4F5"  # casi blanco neutro
    text_value: str = "#FAFAFA"
    text_secondary: str = "#A1A1AA"
    text_card_title: str = "#E4E4E7"
    text_muted: str = "#A1A1AA"  # WCAG AA sobre #0A0A0B
    text_disabled: str = "#71717A"
    text_plot_axis: str = "#A1A1AA"
    text_plot_body: str = "#A1A1AA"

    # Accents — SAP-aligned
    accent_primary: str = "#00A3E0"  # SAP blue
    accent_primary_hover: str = "#0086BA"
    accent_secondary: str = "#5BC0EB"
    accent_secondary_hover: str = "#3DA3CC"
    success: str = "#86BC25"
    success_hover: str = "#6B9B1E"
    warning: str = "#FFB627"
    danger: str = "#E21836"

    # Scrollbar
    scrollbar_thumb: str = "rgba(255,255,255,0.10)"

    # Streamlit native theme
    st_primary: str = "#00A3E0"
    st_bg_widget: str = "#16161A"
    st_text: str = "#F4F4F5"

    # Plotly categorical palette
    plotly_colorway: tuple[str, ...] = (
        "#00A3E0",
        "#86BC25",
        "#5BC0EB",
        "#FFB627",
        "#E21836",
        "#7A5FFF",
        "#00C2A8",
        "#A1A1AA",
    )


@dataclass(frozen=True)
class LightColors:
    """Tokens claros — mismo schema que Colors. Usados con `data-theme="light"`."""

    bg_base: str = "#FAFAFA"
    bg_sidebar_top: str = "#FFFFFF"
    bg_sidebar_bottom: str = "#F4F4F5"
    bg_elev_1: str = "#FFFFFF"
    bg_elev_2: str = "#F4F4F5"
    bg_hoverlabel: str = "#FFFFFF"

    border_subtle: str = "rgba(0,0,0,0.07)"
    border_card: str = "rgba(0,0,0,0.08)"
    border_hover: str = "rgba(0,0,0,0.16)"
    border_plot: str = "rgba(0,0,0,0.06)"
    border_hoverlabel: str = "rgba(0,0,0,0.10)"

    text_primary: str = "#09090B"
    text_value: str = "#09090B"
    text_secondary: str = "#52525B"
    text_card_title: str = "#18181B"
    text_muted: str = "#52525B"
    text_disabled: str = "#A1A1AA"
    text_plot_axis: str = "#52525B"
    text_plot_body: str = "#52525B"

    accent_primary: str = "#0086BA"
    accent_primary_hover: str = "#005F85"
    accent_secondary: str = "#3DA3CC"
    accent_secondary_hover: str = "#2A86AB"
    success: str = "#5E8B0F"
    success_hover: str = "#4A6D0C"
    warning: str = "#B57600"
    danger: str = "#B91229"

    scrollbar_thumb: str = "rgba(0,0,0,0.15)"


@dataclass(frozen=True)
class Spacing:
    xs: str = "0.25rem"
    sm: str = "0.5rem"
    md: str = "1rem"
    lg: str = "1.5rem"
    xl: str = "2rem"
    xxl: str = "3rem"


@dataclass(frozen=True)
class Radii:
    sm: str = "6px"
    md: str = "10px"  # un poco más cerrado (premium)
    lg: str = "14px"
    pill: str = "999px"


@dataclass(frozen=True)
class Shadows:
    sm: str = "0 1px 2px rgba(0,0,0,0.20)"
    md: str = "0 4px 16px rgba(0,0,0,0.18), 0 1px 2px rgba(0,0,0,0.10)"
    focus: str = "0 0 0 3px rgba(0,163,224,0.35)"


@dataclass(frozen=True)
class Type:
    # Inter Tight como display (display tracker -2%); Inter para body.
    family_sans: str = "'Inter Tight','Inter',-apple-system,BlinkMacSystemFont,sans-serif"
    family_display: str = "'Inter Tight','Inter',-apple-system,sans-serif"
    family_plotly: str = "Inter Tight, Inter, -apple-system, sans-serif"
    size_xs: str = "0.7rem"
    size_sm: str = "0.8rem"
    size_md: str = "0.95rem"
    size_lg: str = "1.1rem"
    size_xl: str = "1.5rem"  # hero header
    size_2xl: str = "1.9rem"  # KPI value
    weight_regular: int = 400
    weight_medium: int = 500
    weight_semibold: int = 600
    weight_bold: int = 700
    letter_tight: str = "-0.022em"
    letter_kpi_label: str = "0.06em"

    # Plotly
    size_plot_body: int = 12
    size_plot_axis: int = 11


@dataclass(frozen=True)
class Breakpoints:
    mobile_max: int = 640
    tablet_mid: int = 768
    tablet_max: int = 1024
    desktop_min: int = 1025


@dataclass(frozen=True)
class Layout:
    sidebar_width: str = "280px"  # más estrecho (era 260, pero el real era 336)
    container_max_width: str = "1480px"
    container_padding_top: str = "1.5rem"  # menor — la topbar ya empuja
    container_padding_bottom: str = "2.5rem"
    topbar_height: str = "56px"


@dataclass(frozen=True)
class Tokens:
    colors: Colors = field(default_factory=Colors)
    spacing: Spacing = field(default_factory=Spacing)
    radii: Radii = field(default_factory=Radii)
    shadows: Shadows = field(default_factory=Shadows)
    type: Type = field(default_factory=Type)
    breakpoints: Breakpoints = field(default_factory=Breakpoints)
    layout: Layout = field(default_factory=Layout)
    light: LightColors = field(default_factory=LightColors)


TOKENS = Tokens()
