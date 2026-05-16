"""Overrides del tema claro `[data-theme="light"]`."""

from __future__ import annotations

from dashboard.theme.tokens import Tokens


def build_light_css(t: Tokens) -> str:
    """Bloque `[data-theme="light"]` con todas las custom properties claras."""
    lc = t.light
    return f"""
  [data-theme="light"] {{
    --color-bg-base: {lc.bg_base};
    --color-bg-elev-1: {lc.bg_elev_1};
    --color-bg-elev-2: {lc.bg_elev_2};
    --color-bg-sidebar-top: {lc.bg_sidebar_top};
    --color-bg-sidebar-bottom: {lc.bg_sidebar_bottom};
    --color-bg-hoverlabel: {lc.bg_hoverlabel};
    --color-text-primary: {lc.text_primary};
    --color-text-value: {lc.text_value};
    --color-text-secondary: {lc.text_secondary};
    --color-text-card-title: {lc.text_card_title};
    --color-text-muted: {lc.text_muted};
    --color-text-disabled: {lc.text_disabled};
    --color-accent-primary: {lc.accent_primary};
    --color-accent-primary-hover: {lc.accent_primary_hover};
    --color-accent-secondary: {lc.accent_secondary};
    --color-success: {lc.success};
    --color-warning: {lc.warning};
    --color-danger: {lc.danger};
    --color-border-subtle: {lc.border_subtle};
    --color-border-card: {lc.border_card};
    --color-border-hover: {lc.border_hover};
    --color-border-plot: {lc.border_plot};
    --color-scrollbar-thumb: {lc.scrollbar_thumb};
  }}
  [data-theme="light"] body,
  [data-theme="light"] [data-testid="stAppViewContainer"],
  [data-theme="light"] section[data-testid="stMain"] {{
    background: {lc.bg_base} !important;
    color: {lc.text_primary} !important;
  }}
  [data-theme="light"] section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, {lc.bg_sidebar_top} 0%, {lc.bg_sidebar_bottom} 100%) !important;
    border-right: 1px solid {lc.border_subtle} !important;
  }}
  [data-theme="light"] .topbar {{
    background: rgba(255,255,255,0.80) !important;
    backdrop-filter: blur(18px) saturate(180%) !important;
    -webkit-backdrop-filter: blur(18px) saturate(180%) !important;
    border-bottom: 1px solid {lc.border_subtle} !important;
  }}
  [data-theme="light"] h1, [data-theme="light"] h2,
  [data-theme="light"] h3, [data-theme="light"] h4 {{ color: {lc.text_primary} !important; }}
  [data-theme="light"] .kpi-card,
  [data-theme="light"] .top-card {{
    background: {lc.bg_elev_1} !important;
    border-color: {lc.border_card} !important;
  }}
  [data-theme="light"] .kpi-card .value {{ color: {lc.text_value} !important; }}
  [data-theme="light"] .kpi-card .label,
  [data-theme="light"] .top-card .meta {{ color: {lc.text_muted} !important; }}

  /* ── Texto general (párrafos, labels, markdown, captions) ─────────── */
  [data-theme="light"] body,
  [data-theme="light"] .stApp,
  [data-theme="light"] [data-testid="stAppViewContainer"],
  [data-theme="light"] [data-testid="stMarkdownContainer"],
  [data-theme="light"] [data-testid="stMarkdownContainer"] p,
  [data-theme="light"] [data-testid="stMarkdownContainer"] li,
  [data-theme="light"] [data-testid="stMarkdownContainer"] span,
  [data-theme="light"] [data-testid="stMarkdownContainer"] strong,
  [data-theme="light"] label,
  [data-theme="light"] [data-testid="stWidgetLabel"],
  [data-theme="light"] [data-testid="stWidgetLabel"] *,
  [data-theme="light"] [data-testid="stCaptionContainer"],
  [data-theme="light"] [data-testid="stText"] {{
    color: {lc.text_primary} !important;
  }}
  [data-theme="light"] a {{ color: {lc.accent_primary} !important; }}

  /* ── Métricas (st.metric) ─────────────────────────────────────────── */
  [data-theme="light"] [data-testid="stMetric"],
  [data-theme="light"] [data-testid="stMetricValue"],
  [data-theme="light"] [data-testid="stMetricLabel"],
  [data-theme="light"] [data-testid="stMetricDelta"] {{
    color: {lc.text_primary} !important;
  }}
  [data-theme="light"] [data-testid="stMetricLabel"] {{ color: {lc.text_muted} !important; }}

  /* ── Botones ──────────────────────────────────────────────────────── */
  [data-theme="light"] .stButton > button,
  [data-theme="light"] .stDownloadButton > button,
  [data-theme="light"] [data-testid="stBaseButton-secondary"],
  [data-theme="light"] [data-testid="stBaseButton-secondaryFormSubmit"] {{
    background: {lc.bg_elev_1} !important;
    color: {lc.text_primary} !important;
    border: 1px solid {lc.border_card} !important;
  }}
  [data-theme="light"] .stButton > button:hover,
  [data-theme="light"] .stDownloadButton > button:hover {{
    background: {lc.bg_elev_2} !important;
    border-color: {lc.border_hover} !important;
  }}
  [data-theme="light"] [data-testid="stBaseButton-primary"] {{
    background: {lc.accent_primary} !important;
    color: #FFFFFF !important;
    border: 1px solid {lc.accent_primary} !important;
  }}
  [data-theme="light"] [data-testid="stBaseButton-primary"]:hover {{
    background: {lc.accent_primary_hover} !important;
    border-color: {lc.accent_primary_hover} !important;
  }}

  /* ── Inputs / select / textarea / multiselect ─────────────────────── */
  [data-theme="light"] input,
  [data-theme="light"] textarea,
  [data-theme="light"] select,
  [data-theme="light"] [data-baseweb="input"] input,
  [data-theme="light"] [data-baseweb="select"] > div,
  [data-theme="light"] [data-baseweb="textarea"] textarea {{
    background: {lc.bg_elev_1} !important;
    color: {lc.text_primary} !important;
    border-color: {lc.border_card} !important;
  }}
  [data-theme="light"] [data-baseweb="tag"] {{
    background: {lc.bg_elev_2} !important;
    color: {lc.text_primary} !important;
  }}

  /* ── Tabs, expander, dataframe, popover ───────────────────────────── */
  [data-theme="light"] [data-baseweb="tab"],
  [data-theme="light"] [data-baseweb="tab-list"],
  [data-theme="light"] [data-testid="stExpander"],
  [data-theme="light"] [data-testid="stExpander"] details,
  [data-theme="light"] [data-testid="stExpander"] summary,
  [data-theme="light"] [data-testid="stDataFrame"],
  [data-theme="light"] [data-testid="stDataFrame"] * {{
    color: {lc.text_primary} !important;
  }}
  [data-theme="light"] [data-testid="stExpander"] {{
    background: {lc.bg_elev_1} !important;
    border: 1px solid {lc.border_card} !important;
  }}

  /* ── Plotly: forzar texto y rejilla en claro (template es estático) ── */
  [data-theme="light"] .js-plotly-plot .gtitle,
  [data-theme="light"] .js-plotly-plot .xtick text,
  [data-theme="light"] .js-plotly-plot .ytick text,
  [data-theme="light"] .js-plotly-plot .xtitle,
  [data-theme="light"] .js-plotly-plot .ytitle,
  [data-theme="light"] .js-plotly-plot .legendtext,
  [data-theme="light"] .js-plotly-plot .annotation-text,
  [data-theme="light"] .js-plotly-plot text {{
    fill: {lc.text_primary} !important;
  }}
  [data-theme="light"] .js-plotly-plot .gridlayer path,
  [data-theme="light"] .js-plotly-plot .ygrid,
  [data-theme="light"] .js-plotly-plot .xgrid {{
    stroke: {lc.border_plot} !important;
    opacity: 1 !important;
  }}
  [data-theme="light"] .js-plotly-plot .modebar {{
    background: transparent !important;
  }}
  [data-theme="light"] .js-plotly-plot .modebar-btn path {{
    fill: {lc.text_muted} !important;
  }}
  /* hover labels */
  [data-theme="light"] .js-plotly-plot .hoverlayer .hovertext path,
  [data-theme="light"] .js-plotly-plot .hoverlayer .hovertext rect {{
    fill: {lc.bg_elev_1} !important;
    stroke: {lc.border_card} !important;
  }}
  [data-theme="light"] .js-plotly-plot .hoverlayer .hovertext text {{
    fill: {lc.text_primary} !important;
  }}

  /* ── Override agresivo: Streamlit/BaseWeb inyectan color blanco vía
     Emotion (textColor=#FFFFFF en config). Forzamos texto oscuro en TODO
     descendiente excepto en superficies accent/dark explícitas. ───── */
  [data-theme="light"] .stApp,
  [data-theme="light"] .stApp * {{
    color: {lc.text_primary};
  }}
  /* Restablecer color blanco SOLO donde el fondo es accent (verde) */
  [data-theme="light"] [data-testid="stBaseButton-primary"],
  [data-theme="light"] [data-testid="stBaseButton-primary"] *,
  [data-theme="light"] button[kind="primary"],
  [data-theme="light"] button[kind="primary"] *,
  [data-theme="light"] .skip-link,
  [data-theme="light"] .skip-link *,
  [data-theme="light"] .stAlert[data-baseweb="notification"][kind="error"] *,
  [data-theme="light"] .stAlert[data-baseweb="notification"][kind="success"] *,
  [data-theme="light"] [data-testid="stNotification"][kind="error"] *,
  [data-theme="light"] [data-testid="stNotification"][kind="success"] * {{
    color: #FFFFFF !important;
  }}

  /* Botón primario: dejar texto oscuro sobre verde claro (mejor contraste) */
  [data-theme="light"] button[kind="primary"],
  [data-theme="light"] [data-testid="stBaseButton-primary"] {{
    background: linear-gradient(180deg, {lc.accent_secondary} 0%, {lc.accent_primary} 100%) !important;
    color: #FFFFFF !important;
    border: 1px solid {lc.accent_primary} !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.10) !important;
  }}

  /* Forzar fondos blancos en superficies que usan colores oscuros hardcoded */
  [data-theme="light"] .topbar,
  [data-theme="light"] .kpi-card,
  [data-theme="light"] .top-card,
  [data-theme="light"] .filter-chip,
  [data-theme="light"] [data-testid="stExpander"],
  [data-theme="light"] [data-testid="stPopover"],
  [data-theme="light"] [data-testid="stDataFrame"],
  [data-theme="light"] [data-testid="stTable"],
  [data-theme="light"] [data-baseweb="popover"] > div,
  [data-theme="light"] [data-baseweb="menu"],
  [data-theme="light"] [data-baseweb="select"] [role="listbox"],
  [data-theme="light"] [data-baseweb="select"] > div {{
    background: {lc.bg_elev_1} !important;
    background-image: none !important;
    border-color: {lc.border_card} !important;
  }}

  /* Sidebar children con fondos oscuros explícitos */
  [data-theme="light"] section[data-testid="stSidebar"] * {{
    color: {lc.text_primary};
  }}
  [data-theme="light"] section[data-testid="stSidebar"] [data-baseweb="select"] > div,
  [data-theme="light"] section[data-testid="stSidebar"] input,
  [data-theme="light"] section[data-testid="stSidebar"] textarea {{
    background: {lc.bg_elev_1} !important;
    border-color: {lc.border_card} !important;
  }}

  /* Plotly: forzar fondo del contenedor a blanco (las trazas son transparentes) */
  [data-theme="light"] [data-testid="stPlotlyChart"],
  [data-theme="light"] [data-testid="stPlotlyChart"] > div,
  [data-theme="light"] [data-testid="stPlotlyChart"] .main-svg,
  [data-theme="light"] [data-testid="stPlotlyChart"] .svg-container {{
    background: {lc.bg_base} !important;
  }}
  /* Plotly modebar fondo claro */
  [data-theme="light"] .js-plotly-plot .modebar-group {{
    background: {lc.bg_elev_1} !important;
  }}
  [data-theme="light"] .js-plotly-plot .modebar-btn:hover path {{
    fill: {lc.accent_primary} !important;
  }}

  /* Métricas valor en negro */
  [data-theme="light"] [data-testid="stMetricValue"],
  [data-theme="light"] [data-testid="stMetricValue"] * {{
    color: {lc.text_value} !important;
  }}

  /* Tabs activas */
  [data-theme="light"] [data-baseweb="tab-highlight"] {{
    background: {lc.accent_primary} !important;
  }}

  /* Color-scheme nativo (scrollbars / form controls) */
  [data-theme="light"], [data-theme="light"] .stApp {{
    color-scheme: light !important;
  }}
"""
