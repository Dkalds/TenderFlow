"""Generador del bloque `<style>` inyectado en Streamlit.

Premium refresh:
- Surfaces sólidas (sin glass-morphism agresivo).
- Topbar fija unificada (logo + nav + acciones).
- Light mode via `[data-theme="light"]` en el `<html>`.
- Tipografía Inter Tight con tabular-nums en valores numéricos.
- Bordes 1px sutiles, gradient interior en cards (estilo Vercel/Linear).
- Skeleton shimmer, focus-visible, prefers-reduced-motion, breakpoints.
"""

from __future__ import annotations

from dashboard.theme.tokens import TOKENS, Tokens

# Densidad compacta: reduce el coeficiente que escala paddings/gaps.
COMPACT_DENSITY_CSS = "<style>:root { --density: 0.78; }</style>"


def _light_overrides(t: Tokens) -> str:
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
    background: rgba(255,255,255,0.85) !important;
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
"""


def build_css(t: Tokens = TOKENS) -> str:
    c = t.colors
    ty = t.type
    ra = t.radii
    la = t.layout
    bp = t.breakpoints
    sh = t.shadows
    return f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');

  /* ── Custom properties (single source of truth) ──────────────────── */
  :root {{
    --density: 1;
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
  }}

{_light_overrides(t)}

  /* ── Base ─────────────────────────────────────────────────────────── */
  html, body, [class*="css"] {{
    font-family: {ty.family_sans} !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }}
  body, [data-testid="stAppViewContainer"] {{
    background: var(--color-bg-base) !important;
  }}
  .block-container {{
    padding-top: calc({la.container_padding_top} * var(--density));
    padding-bottom: {la.container_padding_bottom};
    max-width: {la.container_max_width};
  }}
  h1, h2, h3, h4 {{
    font-family: {ty.family_display} !important;
    font-weight: {ty.weight_semibold} !important;
    letter-spacing: {ty.letter_tight};
    color: var(--color-text-primary) !important;
  }}
  h1 {{ font-size: 1.75rem !important; font-weight: {ty.weight_bold} !important; }}
  h2 {{ font-size: 1.25rem !important; color: var(--color-text-secondary) !important; }}
  h3 {{ font-size: {ty.size_md} !important; }}
  h4 {{ font-size: {ty.size_sm} !important; color: var(--color-text-secondary) !important; }}

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

  /* ── Topbar fija premium (logo · nav · acciones) ─────────────────── */
  .topbar {{
    position: sticky;
    top: 0;
    z-index: 100;
    height: var(--topbar-h);
    display: flex;
    align-items: center;
    gap: 24px;
    padding: 0 20px;
    margin: -1.5rem -1rem 18px -1rem;
    background: rgba(0,0,0,0.82);
    backdrop-filter: saturate(160%) blur(14px);
    -webkit-backdrop-filter: saturate(160%) blur(14px);
    border-bottom: 1px solid var(--color-border-subtle);
  }}
  .topbar-brand {{
    display: inline-flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
  }}
  .topbar-brand .brand-logo {{ line-height: 0; }}
  .topbar-brand .brand-logo svg {{
    filter: drop-shadow(0 0 8px rgba(134,188,36,0.35));
  }}
  .topbar-brand .brand-name {{
    font-family: {ty.family_display};
    font-size: 0.95rem;
    font-weight: {ty.weight_semibold};
    color: var(--color-text-primary);
    letter-spacing: -0.012em;
  }}
  .topbar-brand .brand-tag {{
    font-size: 0.65rem;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.10em;
    margin-left: 8px;
    padding-left: 10px;
    border-left: 1px solid var(--color-border-subtle);
  }}
  .topbar-spacer {{ flex: 1; }}
  .topbar-meta {{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: 0.74rem;
    color: var(--color-text-muted);
    padding: 5px 11px;
    border-radius: {ra.pill};
    background: var(--color-bg-elev-1);
    border: 1px solid var(--color-border-subtle);
    white-space: nowrap;
    font-variant-numeric: var(--tab-numerals);
  }}
  .topbar-meta .pulse-dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-success);
    box-shadow: 0 0 0 0 rgba(134,188,36,0.6);
    animation: pulseDot 2s ease-in-out infinite;
  }}
  @keyframes pulseDot {{
    0%, 100% {{ box-shadow: 0 0 0 0 rgba(134,188,36,0.5); }}
    50%      {{ box-shadow: 0 0 0 5px rgba(134,188,36,0); }}
  }}
  .topbar-meta svg {{ flex-shrink: 0; opacity: 0.85; }}

  /* Slot del topbar para el botón refresh y theme toggle de Streamlit */
  .topbar-actions {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }}

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

  /* ── Filtros: agrupación visual ──────────────────────────────────── */
  .filter-group-header {{
    display: flex; align-items: center; gap: 6px;
    font-size: 0.68rem;
    color: var(--color-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: {ty.weight_semibold};
    margin: calc(14px * var(--density)) 0 calc(6px * var(--density)) 0;
  }}
  .filter-group-header svg {{ opacity: 0.65; }}

  /* ── Chips de filtros activos ────────────────────────────────────── */
  .chip-row {{
    display: flex; flex-wrap: wrap; gap: 6px;
    margin: 4px 0 2px 0;
  }}
  .filter-chip {{
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--color-bg-elev-1);
    border: 1px solid var(--color-border-subtle);
    border-radius: {ra.pill};
    padding: 3px 11px;
    font-size: 0.74rem;
    color: var(--color-text-card-title);
    white-space: nowrap;
    line-height: 1.5;
    transition: border-color 0.15s, background 0.15s, transform 0.1s;
  }}
  .filter-chip:hover {{
    border-color: var(--color-accent-primary);
    background: rgba(134,188,36,0.07);
    transform: translateY(-1px);
  }}
  .filter-chip svg {{ opacity: 0.7; flex-shrink: 0; }}

  /* ── KPI Cards (sólidos con leve gradient interior) ───────────────── */
  .kpi-card {{
    background: var(--color-bg-elev-1);
    background-image: linear-gradient(180deg, rgba(255,255,255,0.020), rgba(255,255,255,0));
    border: 1px solid var(--color-border-card);
    border-radius: {ra.md};
    padding: calc(18px * var(--density)) calc(20px * var(--density));
    transition: border-color 0.2s ease, transform 0.18s ease, box-shadow 0.2s ease, background 0.2s ease;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: 100%;
    min-height: calc(122px * var(--density));
    position: relative;
    overflow: hidden;
    /* línea superior sutil estilo Vercel */
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), var(--shadow-sm);
  }}
  .kpi-card:hover {{
    border-color: var(--color-border-hover);
    transform: translateY(-1px);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 6px 22px -6px rgba(134,188,36,0.18), 0 2px 6px rgba(0,0,0,0.20);
    background-image: linear-gradient(180deg, rgba(255,255,255,0.030), rgba(255,255,255,0));
  }}
  .kpi-card .label {{
    color: var(--color-text-muted);
    font-size: 0.685rem;
    font-weight: {ty.weight_semibold};
    text-transform: uppercase;
    letter-spacing: {ty.letter_kpi_label};
    margin-bottom: calc(8px * var(--density));
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 1.8em;
  }}
  .kpi-card .value {{
    color: var(--color-text-value);
    font-family: {ty.family_display};
    font-size: calc(1.85rem * var(--density));
    font-weight: {ty.weight_semibold};   /* 600 — más elegante que 700 */
    line-height: 1.1;
    letter-spacing: -0.025em;
    font-variant-numeric: var(--tab-numerals);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .kpi-card .delta {{
    font-size: 0.74rem;
    margin-top: calc(6px * var(--density));
    font-weight: {ty.weight_medium};
    font-variant-numeric: var(--tab-numerals);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-height: 1.05em;
  }}
  .kpi-card .delta.up {{ color: var(--color-success); }}
  .kpi-card .delta.down {{ color: var(--color-danger); }}
  .kpi-card .icon {{
    color: var(--color-accent-primary); opacity: 0.5;
    position: absolute; top: calc(14px * var(--density)); right: calc(16px * var(--density));
    line-height: 0;
  }}
  .kpi-card .icon svg {{ width: 16px; height: 16px; }}
  .kpi-card .sparkline-wrap {{ margin-top: calc(4px * var(--density)); min-height: 24px; }}
  .kpi-card .anomaly-badge {{
    position: absolute; top: calc(14px * var(--density)); right: calc(40px * var(--density));
    font-size: 0.85rem; color: var(--color-danger);
  }}

  /* ── Top cards ────────────────────────────────────────────────────── */
  .top-card {{
    background: var(--color-bg-elev-1);
    background-image: linear-gradient(180deg, rgba(255,255,255,0.018), rgba(255,255,255,0));
    border: 1px solid var(--color-border-card);
    border-left: 3px solid var(--color-accent-primary);
    border-radius: {ra.md};
    padding: calc(14px * var(--density)) calc(18px * var(--density));
    margin-bottom: calc(10px * var(--density));
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.2s;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: calc(96px * var(--density));
    box-shadow: var(--shadow-sm);
  }}
  .top-card:hover {{
    border-color: var(--color-border-hover);
    transform: translateX(2px);
    box-shadow: -3px 0 12px -4px rgba(134,188,36,0.18), 0 4px 14px rgba(0,0,0,0.18);
  }}
  .top-card .amount {{
    font-family: {ty.family_display};
    font-size: calc(1.2rem * var(--density));
    font-weight: {ty.weight_semibold};
    color: var(--color-accent-primary);
    letter-spacing: -0.015em;
    font-variant-numeric: var(--tab-numerals);
  }}
  .top-card .title {{
    font-size: 0.88rem; color: var(--color-text-card-title); margin: 4px 0; line-height: 1.4;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .top-card .title a {{ color: var(--color-text-card-title); text-decoration: none; }}
  .top-card .title a:hover {{ color: var(--color-accent-primary); }}
  .top-card .meta {{
    font-size: 0.72rem; color: var(--color-text-muted);
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}

  /* ── Breadcrumb ───────────────────────────────────────────────────── */
  .bc {{
    font-size: {ty.size_sm};
    margin-bottom: 2px;
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }}
  .bc-section {{ color: var(--color-text-muted); font-weight: {ty.weight_medium}; }}
  .bc-sep {{ color: var(--color-text-disabled); display: inline-flex; line-height: 0; }}
  .bc-page {{ color: var(--color-accent-primary); font-weight: {ty.weight_semibold}; }}
  .bc-desc {{
    font-size: {ty.size_xs};
    color: var(--color-text-muted);
    margin: 2px 0 0 0;
    line-height: 1.45;
  }}

  /* ── Empty / error states ─────────────────────────────────────────── */
  .empty-state {{
    text-align: center;
    padding: 2.5rem 1rem 1.5rem;
  }}
  .empty-state .es-icon {{
    color: var(--color-text-muted);
    margin-bottom: 0.75rem;
    line-height: 0;
    display: flex; justify-content: center;
  }}
  .empty-state .es-icon svg {{ width: 44px; height: 44px; opacity: 0.7; }}
  .empty-state .es-title {{
    font-family: {ty.family_display};
    font-size: 1.05rem;
    font-weight: {ty.weight_semibold};
    color: var(--color-text-card-title);
    margin-bottom: 0.35rem;
    letter-spacing: -0.012em;
  }}
  .empty-state .es-msg {{
    font-size: 0.85rem;
    color: var(--color-text-muted);
    max-width: 400px;
    margin: 0 auto;
  }}
  .error-banner {{
    border: 1px solid rgba(226,24,54,0.35);
    border-radius: {ra.md};
    padding: 1rem 1.25rem;
    background: rgba(226,24,54,0.06);
    margin-bottom: 0.75rem;
    display: flex;
    gap: 10px;
    align-items: flex-start;
  }}
  .error-banner svg {{ color: var(--color-danger); flex-shrink: 0; margin-top: 2px; }}
  .error-banner strong {{ color: var(--color-text-value); display: block; margin-bottom: 2px; }}
  .error-banner span {{ color: var(--color-text-muted); font-size: 0.875rem; }}

  /* ── Metrics & misc ───────────────────────────────────────────────── */
  div[data-testid="stMetricValue"] {{
    font-family: {ty.family_display};
    font-size: 1.5rem;
    font-variant-numeric: var(--tab-numerals);
    letter-spacing: -0.02em;
  }}
  .stDivider {{ opacity: 0.4; }}
  ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{
    background: var(--color-scrollbar-thumb);
    border-radius: 3px;
  }}
  ::-webkit-scrollbar-thumb:hover {{ background: var(--color-border-hover); }}

  /* ── Chart cards ──────────────────────────────────────────────────── */
  [data-testid="stVerticalBlockBorderWrapper"]:has(.chart-card-header) {{
    background: var(--color-bg-elev-1) !important;
    background-image: linear-gradient(180deg, rgba(255,255,255,0.018), rgba(255,255,255,0)) !important;
    border: 1px solid var(--color-border-card) !important;
    border-radius: {ra.md} !important;
    box-shadow: var(--shadow-sm) !important;
    transition: border-color 0.2s, box-shadow 0.2s;
  }}
  [data-testid="stVerticalBlockBorderWrapper"]:has(.chart-card-header):hover {{
    border-color: var(--color-border-hover) !important;
    box-shadow: 0 4px 18px -6px rgba(134,188,36,0.10), var(--shadow-sm) !important;
  }}
  .chart-card-header {{ margin-bottom: 4px; }}
  .chart-card-title {{
    font-family: {ty.family_display};
    font-size: {ty.size_sm};
    font-weight: {ty.weight_semibold};
    color: var(--color-text-card-title);
    letter-spacing: -0.005em;
    line-height: 1.3;
  }}
  .chart-card-sub {{
    font-size: {ty.size_xs};
    color: var(--color-text-muted);
    margin-top: 2px;
  }}

  .ag-theme-streamlit .ag-row, .ag-theme-balham-dark .ag-row {{
    height: calc(34px * var(--density)) !important;
    min-height: calc(34px * var(--density)) !important;
  }}

  /* ── Focus visible ────────────────────────────────────────────────── */
  button:focus-visible, a:focus-visible, input:focus-visible, select:focus-visible,
  [role="button"]:focus-visible, .filter-chip:focus-visible,
  .kpi-card:focus-visible, .top-card:focus-visible {{
    outline: none !important;
    box-shadow: var(--shadow-focus) !important;
  }}

  /* ── Skeleton shimmer ─────────────────────────────────────────────── */
  @keyframes shimmer {{
    0%   {{ background-position: -600px 0; }}
    100% {{ background-position:  600px 0; }}
  }}
  .skeleton {{
    background: linear-gradient(
      90deg,
      rgba(255,255,255,0.04) 25%,
      rgba(255,255,255,0.09) 50%,
      rgba(255,255,255,0.04) 75%
    );
    background-size: 600px 100%;
    animation: shimmer 1.4s ease-in-out infinite;
    border-radius: {ra.sm};
    margin-bottom: 8px;
  }}
  .skeleton-card {{
    background: linear-gradient(
      90deg,
      rgba(255,255,255,0.04) 25%,
      rgba(255,255,255,0.09) 50%,
      rgba(255,255,255,0.04) 75%
    ) !important;
    background-size: 600px 100% !important;
    animation: shimmer 1.4s ease-in-out infinite !important;
    border-color: transparent !important;
    pointer-events: none;
  }}
  .skeleton-kpi-label, .skeleton-kpi-value, .skeleton-kpi-spark,
  .skeleton-tc-amount, .skeleton-tc-title, .skeleton-tc-meta {{
    border-radius: {ra.sm};
    background: rgba(255,255,255,0.06);
    margin-bottom: calc(8px * var(--density));
  }}
  .skeleton-kpi-label  {{ height: 10px; width: 60%; }}
  .skeleton-kpi-value  {{ height: 28px; width: 75%; }}
  .skeleton-kpi-spark  {{ height: 24px; width: 100%; }}
  .skeleton-tc-amount  {{ height: 22px; width: 40%; }}
  .skeleton-tc-title   {{ height: 14px; width: 90%; }}
  .skeleton-tc-meta    {{ height: 11px; width: 70%; }}

  /* ── Sticky thead en tablas nativas ──────────────────────────────── */
  .stDataFrame thead th {{
    position: sticky;
    top: 0;
    z-index: 1;
    background: var(--color-bg-elev-2);
  }}

  /* ── Animaciones de entrada ───────────────────────────────────────── */
  @keyframes cardFadeUp {{
    from {{ opacity: 0; transform: translateY(8px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
  @keyframes countUp {{
    from {{ opacity: 0; transform: translateY(3px); filter: blur(1px); }}
    to   {{ opacity: 1; transform: translateY(0); filter: blur(0); }}
  }}

  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(1) .kpi-card {{ animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.04s both; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(2) .kpi-card {{ animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.10s both; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(3) .kpi-card {{ animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.16s both; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(4) .kpi-card {{ animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.22s both; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(5) .kpi-card {{ animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.28s both; }}

  .top-card:nth-child(1) {{ animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.06s both; }}
  .top-card:nth-child(2) {{ animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.12s both; }}
  .top-card:nth-child(3) {{ animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.18s both; }}
  .top-card:nth-child(4) {{ animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.24s both; }}
  .top-card:nth-child(5) {{ animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.30s both; }}

  .kpi-card .value {{ animation: countUp 0.45s cubic-bezier(0.22,1,0.36,1) 0.25s both; }}

  /* ── Plotly chart container ───────────────────────────────────────── */
  [data-testid="stPlotlyChart"] > div {{
    border-radius: {ra.md};
    border: none;
    background: transparent;
    padding: 6px 4px;
  }}

  /* ── Sidebar separator sutil ──────────────────────────────────────── */
  section[data-testid="stSidebar"] .stDivider {{
    background: linear-gradient(90deg, transparent, var(--color-border-subtle), transparent) !important;
    height: 1px !important;
    border: none !important;
    opacity: 1 !important;
  }}

  /* ── Status badges ────────────────────────────────────────────────── */
  .status-badge {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 10px;
    border-radius: {ra.pill};
    font-size: 0.74rem;
    font-weight: {ty.weight_medium};
    border: 1px solid transparent;
    line-height: 1.5;
    white-space: nowrap;
    color: var(--badge-color, var(--color-text-muted));
    background: color-mix(in srgb, var(--badge-color, {c.text_muted}) 12%, transparent);
    border-color: color-mix(in srgb, var(--badge-color, {c.text_muted}) 30%, transparent);
    transition: opacity 0.15s ease, transform 0.1s ease;
  }}
  .status-badge svg {{ flex-shrink: 0; }}

  /* ── Tooltip CSS-only ─────────────────────────────────────────────── */
  .has-tooltip {{ position: relative; display: inline-block; }}
  .has-tooltip::after {{
    content: attr(data-tip);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
    background: var(--color-bg-hoverlabel);
    color: var(--color-text-primary);
    border: 1px solid var(--color-border-hover);
    border-radius: {ra.sm};
    padding: 5px 10px;
    font-size: 0.75rem;
    white-space: nowrap;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s ease;
    z-index: 200;
    box-shadow: var(--shadow-md);
  }}
  .has-tooltip:hover::after {{ opacity: 1; }}

  /* ── Search highlight ─────────────────────────────────────────────── */
  mark.search-hl {{
    background: rgba(134,188,36,0.25);
    color: inherit;
    padding: 1px 2px;
    border-radius: 3px;
    font-style: normal;
    font-weight: {ty.weight_medium};
  }}

  /* ── Subtle page background gradient ──────────────────────────────── */
  .block-container::before {{
    content: "";
    position: fixed;
    inset: 0;
    background:
      radial-gradient(ellipse 60% 40% at 18% -8%, rgba(134,188,36,0.045) 0%, transparent 60%),
      radial-gradient(ellipse 50% 40% at 82% 105%, rgba(134,188,36,0.030) 0%, transparent 60%);
    pointer-events: none;
    z-index: -1;
  }}

  /* ── Responsive — tablet (≤ {bp.tablet_max}px) ───────────────────── */
  @media (max-width: {bp.tablet_max}px) {{
    .block-container {{
      max-width: 100% !important;
      padding-left: 1rem !important;
      padding-right: 1rem !important;
    }}
    section[data-testid="stSidebar"] {{
      width: 240px !important;
      min-width: 240px !important;
      max-width: 240px !important;
    }}
    .kpi-card {{ padding: 14px 16px; }}
    .kpi-card .value {{ font-size: 1.4rem; }}
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
      min-width: 48% !important;
    }}
    .topbar {{ gap: 14px; padding: 0 12px; }}
    .topbar-brand .brand-tag {{ display: none; }}
  }}

  /* ── Responsive — mobile (≤ {bp.mobile_max}px) ───────────────────── */
  @media (max-width: {bp.mobile_max}px) {{
    .block-container {{
      padding-left: 0.5rem !important;
      padding-right: 0.5rem !important;
    }}
    [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; }}
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
      flex: 1 1 100% !important;
      min-width: 100% !important;
    }}
    .kpi-card {{ min-height: auto; }}
    .kpi-card {{
      padding: 12px 14px;
      min-height: 100px;
    }}
    .kpi-card .value {{
      font-size: 1.3rem;
    }}
    .kpi-card .label {{
      font-size: 0.65rem;
    }}
    .topbar {{ height: auto; padding: 8px 12px; flex-wrap: wrap; }}
    .topbar-meta {{ display: none; }}
  }}

  /* ── Responsive — iPad portrait (≤ {bp.tablet_mid}px) ─────────────── */
  @media (max-width: {bp.tablet_mid}px) {{
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
      flex: 1 1 48% !important;
      min-width: 48% !important;
    }}
    /* Full width only for chart containers */
    [data-testid="stHorizontalBlock"] > [data-testid="column"]:has([data-testid="stPlotlyChart"]) {{
      flex: 1 1 100% !important;
      min-width: 100% !important;
    }}
    [data-testid="stPlotlyChart"] {{ min-height: 280px; }}
  }}

  /* ── Mobile scroll indicator en tablas ───────────────────────────── */
  @media (max-width: {bp.mobile_max}px) {{
    .stDataFrame {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    [data-testid="stDataFrame"] {{ position: relative; }}
    [data-testid="stDataFrame"]::after {{
      content: "";
      position: absolute;
      top: 0; right: 0; bottom: 0;
      width: 28px;
      background: linear-gradient(to right, transparent, var(--color-bg-base));
      pointer-events: none;
    }}
  }}

  /* ── Skip-link ────────────────────────────────────────────────────── */
  .skip-link {{
    position: absolute; left: -9999px; top: auto;
    width: 1px; height: 1px; overflow: hidden;
    z-index: 9999;
    padding: 0.75rem 1.5rem;
    background: var(--color-accent-primary);
    color: var(--color-bg-base);
    font-weight: {ty.weight_semibold};
    border-radius: {ra.sm};
    text-decoration: none;
  }}
  .skip-link:focus {{
    left: 1rem; top: 0.5rem;
    width: auto; height: auto; overflow: visible;
  }}

  /* ── prefers-reduced-motion ───────────────────────────────────────── */
  @media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
      animation-duration: 0.001s !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.001s !important;
    }}
    .topbar-meta .pulse-dot {{ animation: none !important; }}
  }}
</style>
"""
