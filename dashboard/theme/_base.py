"""CSS base: variables, tipografía, chrome de Streamlit, sidebar, layout."""

from __future__ import annotations

from dashboard.theme.tokens import Tokens


def build_base_css(t: Tokens) -> str:
    c = t.colors
    ty = t.type
    ra = t.radii
    la = t.layout
    sh = t.shadows
    return f"""
  @import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&family=Inter+Tight:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');

  /* ── color-scheme declaration para scrollbars nativos ───────────── */
  :root {{ color-scheme: dark; }}
  [data-theme="light"] {{ color-scheme: light; }}

  /* ── Custom properties (single source of truth) ──────────────────── */
  :root {{
    --density: 0.85;
    --color-bg-base: {c.bg_base};
    --color-bg-elev-1: {c.bg_elev_1};
    --color-bg-elev-2: {c.bg_elev_2};
    --color-bg-sidebar-top: {c.bg_sidebar_top};
    --color-bg-sidebar-bottom: {c.bg_sidebar_bottom};
    --color-bg-hoverlabel: {c.bg_hoverlabel};
    --color-text-primary: {c.text_primary};
    --color-text-value: {c.text_value};
    --color-text-secondary: {c.text_secondary};
    --color-text-card-title: {c.text_card_title};
    --color-text-muted: {c.text_muted};
    --color-text-disabled: {c.text_disabled};
    --color-accent-primary: {c.accent_primary};
    --color-accent-primary-hover: {c.accent_primary_hover};
    --color-accent-secondary: {c.accent_secondary};
    --color-success: {c.success};
    --color-warning: {c.warning};
    --color-danger: {c.danger};
    --color-border-subtle: {c.border_subtle};
    --color-border-card: {c.border_card};
    --color-border-hover: {c.border_hover};
    --color-border-plot: {c.border_plot};
    --color-scrollbar-thumb: {c.scrollbar_thumb};
    --radius-sm: {ra.sm};
    --radius-md: {ra.md};
    --radius-lg: {ra.lg};
    --radius-pill: {ra.pill};
    --shadow-sm: {sh.sm};
    --shadow-md: {sh.md};
    --shadow-focus: {sh.focus};
    --topbar-h: {la.topbar_height};
    --tab-numerals: tabular-nums;
    --font-feature: "ss01","ss02","cv11";
  }}

  /* ── Base ─────────────────────────────────────────────────────────── */
  html, body, [class*="css"] {{
    font-family: {ty.family_sans} !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    font-feature-settings: var(--font-feature);
  }}
  body, [data-testid="stAppViewContainer"] {{
    background: var(--color-bg-base) !important;
  }}
  .block-container {{
    padding-top: calc({la.container_padding_top} * var(--density));
    padding-bottom: {la.container_padding_bottom};
    max-width: {la.container_max_width};
  }}
  /* Headings: [data-testid="stApp"] prefix gives (0,1,1) > Emotion (0,1,0) — no !important needed */
  [data-testid="stApp"] :is(h1, h2, h3, h4) {{
    font-family: {ty.family_display};
    font-weight: {ty.weight_semibold};
    letter-spacing: {ty.letter_tight};
    color: var(--color-text-primary);
  }}
  [data-testid="stApp"] h1 {{ font-size: 1.75rem; font-weight: {ty.weight_bold}; letter-spacing: {ty.letter_display}; }}
  [data-testid="stApp"] h2 {{ font-size: 1.25rem; color: var(--color-text-secondary); }}
  [data-testid="stApp"] h3 {{ font-size: {ty.size_md}; }}
  [data-testid="stApp"] h4 {{ font-size: {ty.size_sm}; color: var(--color-text-secondary); }}

  /* ── Hide Streamlit chrome ────────────────────────────────────────── */
  #MainMenu {{ visibility: hidden !important; }}
  header[data-testid="stHeader"] {{
    background: transparent !important;
    height: 0 !important;
  }}
  [data-testid="stToolbar"] {{ visibility: hidden !important; }}
  [data-testid="stExpandSidebarButton"] {{
    visibility: visible !important;
    display: block !important;
    position: fixed !important;
    top: 50% !important;
    left: 0 !important;
    transform: translateY(-50%) !important;
    z-index: 999 !important;
    background: var(--color-bg-elev-1) !important;
    border: 1px solid var(--color-border-subtle) !important;
    border-left: none !important;
    border-radius: 0 {ra.sm} {ra.sm} 0 !important;
    padding: 12px 8px !important;
    box-shadow: var(--shadow-md) !important;
    transition: background 0.2s ease, border-color 0.2s ease !important;
  }}
  [data-testid="stExpandSidebarButton"]:hover {{
    background: rgba(134,188,36,0.08) !important;
    border-color: var(--color-accent-primary) !important;
  }}
  [data-testid="stExpandSidebarButton"] svg {{
    color: var(--color-accent-primary) !important;
    width: 18px !important;
    height: 18px !important;
  }}
  [data-testid="stAppDeployButton"], [data-testid="stMainMenu"] {{ display: none !important; }}
  footer {{ visibility: hidden !important; height: 0 !important; }}
  div[data-testid="stDecoration"] {{ display: none !important; }}
  div[data-testid="stStatusWidget"] {{ display: none !important; }}
  [data-testid="stSidebarNav"] {{ display: none !important; }}
  [data-testid="stSidebarNavSeparator"] {{ display: none !important; }}
  a[href*="streamlit.io"][target="_blank"] {{ display: none !important; }}

  /* ── Sidebar ──────────────────────────────────────────────────────── */
  section[data-testid="stSidebar"] {{
    width: {la.sidebar_width} !important;
    min-width: {la.sidebar_width} !important;
    max-width: {la.sidebar_width} !important;
    background: linear-gradient(180deg, var(--color-bg-sidebar-top) 0%, var(--color-bg-sidebar-bottom) 100%) !important;
    border-right: 1px solid var(--color-border-subtle) !important;
    box-shadow: 1px 0 0 0 var(--color-border-subtle);
  }}
  section[data-testid="stSidebar"] > div {{ padding-top: {t.spacing.md}; }}

  section[data-testid="stSidebar"][aria-expanded="false"] {{
    width: 0 !important; min-width: 0 !important; max-width: 0 !important;
    overflow: hidden !important;
  }}
  section[data-testid="stSidebar"][aria-expanded="false"] ~ section[data-testid="stMain"] .block-container,
  [data-testid="stAppViewBlockContainer"] {{
    max-width: 100% !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    transition: max-width 0.3s ease, padding 0.3s ease;
  }}
  section[data-testid="stSidebar"] {{
    transition: width 0.3s ease, min-width 0.3s ease, max-width 0.3s ease !important;
  }}
  .block-container {{
    transition: max-width 0.3s ease, padding 0.3s ease !important;
  }}

  /* ── Sidebar premium ─────────────────────────────────────────────── */
  section[data-testid="stSidebar"] {{
    background: linear-gradient(180deg,
      var(--color-bg-sidebar-top) 0%,
      var(--color-bg-sidebar-bottom) 100%
    ) !important;
    border-right: 1px solid var(--color-border-subtle) !important;
  }}
  /* Separadores tipo fade lateral */
  section[data-testid="stSidebar"] .stDivider {{
    background: linear-gradient(90deg, transparent, var(--color-border-subtle), transparent) !important;
    height: 1px !important;
    border: none !important;
    opacity: 1 !important;
  }}
  /* Labels de sección en sidebar */
  section[data-testid="stSidebar"] .stMarkdown p {{
    font-size: 0.78rem;
    font-weight: {ty.weight_medium};
    color: var(--color-text-muted);
    letter-spacing: 0.04em;
  }}
  /* Selectboxes y multiselects en sidebar — fondo coherente */
  section[data-testid="stSidebar"] [data-baseweb="select"] {{
    background: var(--color-bg-elev-1) !important;
    border-color: var(--color-border-subtle) !important;
  }}
  section[data-testid="stSidebar"] [data-baseweb="select"]:hover {{
    border-color: var(--color-border-hover) !important;
  }}
  /* Sidebar nav active indicator */
  section[data-testid="stSidebar"] [data-testid="stRadio"] label {{
    border-radius: {ra.sm};
    padding: 6px 10px;
    transition: background 120ms ease, color 120ms ease;
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
  }}
  section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {{
    background: rgba(134,188,36,0.06) !important;
    color: var(--color-accent-primary) !important;
  }}
  section[data-testid="stSidebar"] [data-testid="stRadio"] [aria-checked="true"] + div label,
  section[data-testid="stSidebar"] [data-testid="stRadio"] input:checked + label {{
    color: var(--color-accent-primary) !important;
    font-weight: {ty.weight_semibold} !important;
    background: rgba(134,188,36,0.08) !important;
    box-shadow: inset 3px 0 0 var(--color-accent-primary);
  }}

  /* ── Layout: column gap & vertical alignment ─────────────────────── */
  [data-testid="stHorizontalBlock"] {{
    gap: calc(14px * var(--density)) !important;
    align-items: stretch !important;
  }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
    display: flex; flex-direction: column;
  }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"] > div {{ height: 100%; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"] [data-testid="stMarkdownContainer"] {{
    height: 100%;
  }}

  .block-container h2 {{ margin-top: calc(28px * var(--density)) !important; margin-bottom: calc(10px * var(--density)) !important; }}
  .block-container h3 {{ margin-top: calc(20px * var(--density)) !important; margin-bottom: calc(6px * var(--density)) !important; }}
  .block-container h4 {{ margin-top: calc(14px * var(--density)) !important; margin-bottom: calc(4px * var(--density)) !important; }}
  [data-testid="stPlotlyChart"] {{ margin-bottom: calc(8px * var(--density)); }}

  /* ── Brand del sidebar (legacy — fallback si no se usa topbar) ───── */
  .brand {{
    display: flex; align-items: center; gap: 10px;
    padding: 4px 4px 0 4px;
    margin-bottom: calc(14px * var(--density));
  }}
  .brand .brand-logo {{ flex-shrink: 0; line-height: 0; }}
  .brand .brand-text {{ display: flex; flex-direction: column; line-height: 1.15; }}
  .brand .brand-name {{
    font-family: {ty.family_display};
    font-size: 0.95rem;
    font-weight: {ty.weight_semibold};
    color: var(--color-text-primary);
    letter-spacing: -0.012em;
  }}
  .brand .brand-tag {{
    font-size: 0.65rem;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.10em;
    margin-top: 2px;
  }}

  /* ── Metrics & misc ───────────────────────────────────────────────── */
  div[data-testid="stMetricValue"] {{
    font-family: {ty.family_display};
    font-size: 1.5rem;
    font-variant-numeric: var(--tab-numerals);
    font-feature-settings: var(--font-feature), "tnum";
    letter-spacing: {ty.letter_display};
  }}
  td, th {{
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
  }}
  .stDivider {{ opacity: 0.4; }}
  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{
    background: var(--color-scrollbar-thumb);
    border-radius: 3px;
  }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--color-border-hover); }}

  /* ── Plotly chart container ───────────────────────────────────────── */
  [data-testid="stPlotlyChart"] > div {{
    border-radius: {ra.md};
    border: none;
    background: transparent;
    padding: 6px 4px;
  }}
"""
