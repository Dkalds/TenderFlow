"""Design tokens — única fuente de verdad del tema corporativo.

Dataclasses frozen: permiten tipado estricto, hashing y consumo directo desde
CSS (f-strings) y Plotly (dict layout).

Los valores actuales replican el CSS inline pre-refactor (app.py:32-103 y
_premium layout en :138-158). La mejora de contraste WCAG AA (#808080 →
#A8A8A8) se introduce en Fase 4 sobre `Colors.text_muted`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Colors:
    # Base surfaces
    bg_base: str = "#0E1117"
    bg_sidebar_top: str = "#0D0D0D"
    bg_sidebar_bottom: str = "#111111"
    bg_elev_1: str = "rgba(255,255,255,0.03)"  # kpi-card bg
    bg_elev_2: str = "rgba(255,255,255,0.025)"  # top-card bg
    bg_hoverlabel: str = "#1A1A1A"

    # Borders
    border_subtle: str = "rgba(255,255,255,0.06)"
    border_card: str = "rgba(255,255,255,0.05)"
    border_hover: str = "rgba(255,255,255,0.12)"
    border_plot: str = "rgba(255,255,255,0.08)"
    border_hoverlabel: str = "rgba(255,255,255,0.1)"

    # Text
    text_primary: str = "#E8E8E8"
    text_value: str = "#F0F0F0"
    text_secondary: str = "#B0B0B0"
    text_card_title: str = "#E0E0E0"
    text_muted: str = "#A8A8A8"  # WCAG AA 4.7:1 sobre #0E1117
    text_disabled: str = "#707070"  # WCAG AA ≥4.5:1 sobre #0E1117 (era #555555, 2.8:1)
    text_plot_axis: str = "#A8A8A8"
    text_plot_body: str = "#A0A0A0"

    # Accents — identidad SAP-aligned con azul como primario (Refresh visual).
    # `accent_primary` impulsa los acentos de marca (KPIs, top-cards, breadcrumb,
    # primaryColor de Streamlit). El verde se reserva al rol semántico
    # "positivo / éxito" (`success`).
    accent_primary: str = "#00A3E0"  # SAP blue
    accent_primary_hover: str = "#0083B3"
    accent_secondary: str = "#5BC0EB"  # azul claro complementario
    accent_secondary_hover: str = "#3DA3CC"
    success: str = "#86BC25"  # SAP green — solo para "positivo"
    success_hover: str = "#6B9B1E"
    warning: str = "#FFB627"
    danger: str = "#E21836"

    # Scrollbar
    scrollbar_thumb: str = "rgba(255,255,255,0.08)"

    # Streamlit native theme (.streamlit/config.toml).
    # Alineado con `accent_primary` para coherencia visual entre widgets nativos
    # y CSS custom.
    st_primary: str = "#00A3E0"
    st_bg_widget: str = "#1A1F2C"  # secondaryBackgroundColor
    st_text: str = "#E8ECF1"  # textColor

    # Plotly categorical palette (orden = colorway). Azul primario primero,
    # verde "success" segundo, paleta extendida profesional a continuación.
    plotly_colorway: tuple[str, ...] = (
        "#00A3E0",  # primary blue
        "#86BC25",  # success green
        "#5BC0EB",  # light blue
        "#FFB627",  # warning amber
        "#E21836",  # danger red
        "#7A5FFF",  # violet
        "#00C2A8",  # teal
        "#A8A8A8",  # neutral grey
    )


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
    md: str = "12px"
    lg: str = "16px"
    pill: str = "999px"


@dataclass(frozen=True)
class Shadows:
    sm: str = "0 1px 3px rgba(0,0,0,0.12)"
    md: str = "0 2px 12px rgba(0,0,0,0.15)"
    focus: str = "0 0 0 3px rgba(0,163,224,0.35)"


@dataclass(frozen=True)
class Type:
    family_sans: str = "'Inter',-apple-system,BlinkMacSystemFont,sans-serif"
    family_plotly: str = "Inter, -apple-system, sans-serif"
    size_xs: str = "0.7rem"
    size_sm: str = "0.8rem"
    size_md: str = "0.95rem"
    size_lg: str = "1.1rem"
    size_xl: str = "1.35rem"
    size_2xl: str = "1.7rem"
    weight_regular: int = 400
    weight_medium: int = 500
    weight_semibold: int = 600
    weight_bold: int = 700
    letter_tight: str = "-0.025em"
    letter_kpi_label: str = "0.07em"

    # Plotly
    size_plot_body: int = 12
    size_plot_axis: int = 11


@dataclass(frozen=True)
class Breakpoints:
    mobile_max: int = 640  # < 640px
    tablet_mid: int = 768  # iPad portrait
    tablet_max: int = 1024  # 641–1024
    desktop_min: int = 1025  # ≥ 1025


@dataclass(frozen=True)
class Layout:
    sidebar_width: str = "260px"
    container_max_width: str = "1440px"
    container_padding_top: str = "3.5rem"
    container_padding_bottom: str = "2rem"


@dataclass(frozen=True)
class Tokens:
    colors: Colors = field(default_factory=Colors)
    spacing: Spacing = field(default_factory=Spacing)
    radii: Radii = field(default_factory=Radii)
    shadows: Shadows = field(default_factory=Shadows)
    type: Type = field(default_factory=Type)
    breakpoints: Breakpoints = field(default_factory=Breakpoints)
    layout: Layout = field(default_factory=Layout)


TOKENS = Tokens()
