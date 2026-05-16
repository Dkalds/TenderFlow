"""Design tokens — única fuente de verdad del tema corporativo.

Paleta oficial:
  #86BC24  Verde corporativo  — color principal / acentos
  #0B0B0D  Negro azulado      — tipografía y branding (reemplaza #000000 plano)
  #4A4A4A  Gris oscuro        — textos secundarios
  #75787B  Gris medio         — fondos y separadores
  #D0D0CE  Gris claro         — fondos suaves
  #FFFFFF  Blanco             — espacios y limpieza visual

Dark mode: negro azulado #0B0B0D como base (no negro plano); elevaciones
           sutiles #111114 / #16161A; grises corporativos para texto/bordes.
Light mode: blanco como base, gris claro #D0D0CE para elevaciones,
            gris medio #75787B para separadores, gris oscuro #4A4A4A para
            textos secundarios, negro #000000 para texto primario.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Colors:
    # Base surfaces (dark mode — negro azulado, más rico que negro plano)
    bg_base: str = "#0B0B0D"  # negro azulado corporativo
    bg_sidebar_top: str = "#0E0E11"
    bg_sidebar_bottom: str = "#0B0B0D"
    bg_elev_1: str = "#111114"  # surface 1 (cards)
    bg_elev_2: str = "#16161A"  # surface 2 (cards activas / tablas)
    bg_hoverlabel: str = "#1C1C21"

    # Borders — derivados del gris medio #75787B con opacidad sobre negro azulado
    border_subtle: str = "rgba(117,120,123,0.18)"  # #75787B @18%
    border_card: str = "rgba(117,120,123,0.22)"  # #75787B @22%
    border_hover: str = "rgba(134,188,36,0.35)"  # verde corporativo en hover
    border_plot: str = "rgba(117,120,123,0.12)"  # #75787B @12%
    border_hoverlabel: str = "rgba(117,120,123,0.30)"  # #75787B @30%

    # Text — blanco corporativo + grises de la paleta oficial
    text_primary: str = "#F0F0F0"  # blanco levemente cálido (menos harsh que #FFF)
    text_value: str = "#FFFFFF"  # blanco puro para valores KPI
    text_secondary: str = "#D0D0CE"  # gris claro corporativo
    text_card_title: str = "#D0D0CE"  # gris claro corporativo
    text_muted: str = "#75787B"  # gris medio corporativo
    text_disabled: str = "#4A4A4A"  # gris oscuro corporativo
    text_plot_axis: str = "#75787B"  # gris medio corporativo
    text_plot_body: str = "#D0D0CE"  # gris claro corporativo

    # Accents — verde corporativo #86BC24
    accent_primary: str = "#86BC24"  # verde corporativo
    accent_primary_hover: str = "#95CC2C"  # verde más claro en hover (glow)
    accent_secondary: str = "#A8D44C"  # verde claro complementario
    accent_secondary_hover: str = "#8FBA35"
    success: str = "#86BC24"  # verde = éxito (mismo acento)
    success_hover: str = "#6B9B1E"
    warning: str = "#FFB627"
    danger: str = "#E21836"

    # Scrollbar — gris medio corporativo
    scrollbar_thumb: str = "rgba(117,120,123,0.28)"  # #75787B @28%

    # Streamlit native theme
    st_primary: str = "#86BC24"
    st_bg_widget: str = "#16161A"
    st_text: str = "#F0F0F0"

    # Plotly categorical palette (OKLCH-inspired, perceptually uniform)
    plotly_colorway: tuple[str, ...] = (
        "#86BC24",  # verde corporativo (principal)
        "#5BC0EB",  # azul cielo
        "#FFB627",  # ámbar
        "#A8D44C",  # verde claro
        "#9B8FFF",  # lavender
        "#00C2A8",  # teal
        "#FF7849",  # coral
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
    """Escala 4-pt estricta para ritmo vertical consistente."""

    xs: str = "4px"
    sm: str = "8px"
    md: str = "12px"
    lg: str = "16px"
    xl: str = "24px"
    xxl: str = "32px"
    xxxl: str = "48px"
    xxxxl: str = "64px"


@dataclass(frozen=True)
class Radii:
    sm: str = "6px"
    md: str = "10px"  # un poco más cerrado (premium)
    lg: str = "14px"
    pill: str = "999px"


@dataclass(frozen=True)
class Shadows:
    """Sombras de 2 capas con tinte de marca verde corporativo."""

    sm: str = "0 1px 0 rgba(255,255,255,0.04) inset, 0 1px 3px rgba(0,0,0,0.32)"
    md: str = "0 1px 0 rgba(255,255,255,0.04) inset, 0 8px 24px -8px rgba(0,0,0,0.55), 0 2px 6px rgba(134,188,36,0.06)"
    lg: str = "0 1px 0 rgba(255,255,255,0.04) inset, 0 20px 40px -12px rgba(0,0,0,0.65), 0 4px 12px rgba(134,188,36,0.08)"
    focus: str = "0 0 0 3px rgba(134,188,36,0.40)"  # verde corporativo


@dataclass(frozen=True)
class Type:
    # Geist Sans como display (Vercel, MIT); Inter Tight como fallback; Inter para body.
    family_sans: str = "'Geist','Inter Tight','Inter',-apple-system,BlinkMacSystemFont,sans-serif"
    family_display: str = "'Geist','Inter Tight','Inter',-apple-system,sans-serif"
    family_plotly: str = "Geist, Inter Tight, Inter, -apple-system, sans-serif"
    family_mono: str = "'Geist Mono','JetBrains Mono',ui-monospace,monospace"
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
    letter_tight: str = "-0.03em"  # display — más premium
    letter_body: str = "-0.01em"  # body text
    letter_kpi_label: str = "0.05em"  # labels uppercase
    letter_display: str = "-0.03em"  # hero / KPI values

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
    sidebar_width: str = "240px"  # estrecho = más espacio para datos
    container_max_width: str = "1600px"  # más ancho en pantallas grandes
    container_padding_top: str = "1.5rem"
    container_padding_bottom: str = "2.5rem"
    topbar_height: str = "64px"  # más alto = más premium


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
