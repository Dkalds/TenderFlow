"""Design tokens — única fuente de verdad del tema corporativo.

Paleta oficial:
  #86BC24  Verde corporativo  — color principal / acentos
  #000000  Negro              — tipografía y branding
  #4A4A4A  Gris oscuro        — textos secundarios
  #75787B  Gris medio         — fondos y separadores
  #D0D0CE  Gris claro         — fondos suaves
  #FFFFFF  Blanco             — espacios y limpieza visual

Dark mode: superficies en negro puro; grises corporativos para texto/bordes.
Light mode: blanco como base, gris claro #D0D0CE para elevaciones,
            gris medio #75787B para separadores, gris oscuro #4A4A4A para
            textos secundarios, negro #000000 para texto primario.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Colors:
    # Base surfaces (dark mode — negro corporativo #000000)
    bg_base: str = "#000000"  # negro puro corporativo
    bg_sidebar_top: str = "#0A0A0A"
    bg_sidebar_bottom: str = "#000000"
    bg_elev_1: str = "#0D0D0D"  # surface 1 (cards)
    bg_elev_2: str = "#141414"  # surface 2 (cards activas / tablas)
    bg_hoverlabel: str = "#1A1A1A"

    # Borders — derivados del gris medio #75787B con opacidad sobre negro
    border_subtle: str = "rgba(117,120,123,0.18)"  # #75787B @18%
    border_card: str = "rgba(117,120,123,0.20)"  # #75787B @20%
    border_hover: str = "rgba(117,120,123,0.45)"  # #75787B @45%
    border_plot: str = "rgba(117,120,123,0.15)"  # #75787B @15%
    border_hoverlabel: str = "rgba(117,120,123,0.30)"  # #75787B @30%

    # Text — blanco corporativo + grises de la paleta oficial
    text_primary: str = "#FFFFFF"  # blanco corporativo
    text_value: str = "#FFFFFF"  # blanco puro para valores KPI
    text_secondary: str = "#D0D0CE"  # gris claro corporativo
    text_card_title: str = "#D0D0CE"  # gris claro corporativo
    text_muted: str = "#75787B"  # gris medio corporativo
    text_disabled: str = "#4A4A4A"  # gris oscuro corporativo
    text_plot_axis: str = "#75787B"  # gris medio corporativo
    text_plot_body: str = "#D0D0CE"  # gris claro corporativo

    # Accents — verde corporativo #86BC24 + negro #000000
    accent_primary: str = "#86BC24"  # verde corporativo
    accent_primary_hover: str = "#6B9B1E"  # verde oscuro hover
    accent_secondary: str = "#A8D44C"  # verde claro complementario
    accent_secondary_hover: str = "#8FBA35"
    success: str = "#86BC24"  # verde = éxito (mismo acento)
    success_hover: str = "#6B9B1E"
    warning: str = "#FFB627"
    danger: str = "#E21836"

    # Scrollbar — gris medio corporativo
    scrollbar_thumb: str = "rgba(117,120,123,0.30)"  # #75787B @30%

    # Streamlit native theme
    st_primary: str = "#86BC24"
    st_bg_widget: str = "#141414"
    st_text: str = "#FFFFFF"

    # Plotly categorical palette
    plotly_colorway: tuple[str, ...] = (
        "#86BC24",  # verde corporativo (principal)
        "#A8D44C",  # verde claro
        "#FFB627",  # ámbar
        "#00C2A8",  # teal
        "#7A5FFF",  # púrpura
        "#5BC0EB",  # azul claro
        "#E21836",  # rojo
        "#75787B",  # gris medio corporativo
    )


@dataclass(frozen=True)
class LightColors:
    """Tokens claros — mismo schema que Colors. Usados con `data-theme="light"`."""

    # Base surfaces — blanco corporativo + gris claro #D0D0CE
    bg_base: str = "#FFFFFF"  # blanco corporativo
    bg_sidebar_top: str = "#FFFFFF"  # blanco
    bg_sidebar_bottom: str = "#D0D0CE"  # gris claro corporativo
    bg_elev_1: str = "#FFFFFF"  # blanco (cards)
    bg_elev_2: str = "#D0D0CE"  # gris claro corporativo (tablas/activas)
    bg_hoverlabel: str = "#FFFFFF"

    # Borders — derivados del gris medio #75787B
    border_subtle: str = "rgba(117,120,123,0.20)"  # #75787B @20%
    border_card: str = "rgba(117,120,123,0.25)"  # #75787B @25%
    border_hover: str = "rgba(117,120,123,0.55)"  # #75787B @55%
    border_plot: str = "rgba(117,120,123,0.18)"  # #75787B @18%
    border_hoverlabel: str = "rgba(117,120,123,0.30)"  # #75787B @30%

    # Text — negro y grises corporativos sobre blanco
    text_primary: str = "#000000"  # negro corporativo
    text_value: str = "#000000"  # negro corporativo para valores KPI
    text_secondary: str = "#4A4A4A"  # gris oscuro corporativo
    text_card_title: str = "#000000"  # negro corporativo
    text_muted: str = "#75787B"  # gris medio corporativo
    text_disabled: str = "#D0D0CE"  # gris claro corporativo
    text_plot_axis: str = "#75787B"  # gris medio corporativo
    text_plot_body: str = "#4A4A4A"  # gris oscuro corporativo

    # Accents — verde más oscuro para WCAG AA sobre blanco
    accent_primary: str = "#6B9B1E"  # verde oscuro (contraste ≥4.5:1 sobre #FFF)
    accent_primary_hover: str = "#527A17"
    accent_secondary: str = "#86BC24"
    accent_secondary_hover: str = "#6B9B1E"
    success: str = "#6B9B1E"
    success_hover: str = "#527A17"
    warning: str = "#B57600"
    danger: str = "#B91229"

    # Scrollbar — gris medio corporativo
    scrollbar_thumb: str = "rgba(117,120,123,0.35)"  # #75787B @35%


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
    focus: str = "0 0 0 3px rgba(134,188,36,0.35)"  # verde corporativo


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
