"""Generador del bloque `<style>` inyectado en Streamlit.

`build_css(tokens)` devuelve la cadena `<style>…</style>` completa incluyendo:
- Estilos base (Fase 1)
- Shimmer animation para loading skeletons (Fase 3)
- Media queries responsive 1024 / 768 / 640 px (Fase 3 + mejoras-visuales)
- prefers-reduced-motion (Fase 3)
- Focus-visible ring y skip-to-content (Fase 4)
- Refresh visual (azul SAP, hide chrome nativo, header/chips/density real)
- Status badges, tooltip CSS-only, search highlight (mejoras-visuales)
- Sticky thead, micro-interacciones, scroll indicator móvil (mejoras-visuales)
"""

from __future__ import annotations

from dashboard.theme.tokens import TOKENS, Tokens

# Densidad compacta: reduce el coeficiente que escala paddings/gaps en cards,
# tablas y separadores (todas las reglas usan `calc(N * var(--density))`).
COMPACT_DENSITY_CSS = "<style>:root { --density: 0.78; }</style>"


def build_css(t: Tokens = TOKENS) -> str:
    c = t.colors
    ty = t.type
    ra = t.radii
    la = t.layout
    bp = t.breakpoints
    sh = t.shadows
    return f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

  /* ── Custom properties (consumibles por componentes) ─────────────── */
  :root {{
    --density: 1;
    --color-bg-base: {c.bg_base};
    --color-text-primary: {c.text_primary};
    --color-text-secondary: {c.text_secondary};
    --color-text-card-title: {c.text_card_title};
    --color-text-muted: {c.text_muted};
    --color-text-disabled: {c.text_disabled};
    --color-accent-primary: {c.accent_primary};
    --color-accent-primary-hover: {c.accent_primary_hover};
    --color-success: {c.success};
    --color-warning: {c.warning};
    --color-danger: {c.danger};
    --color-border-subtle: {c.border_subtle};
    --color-border-card: {c.border_card};
    --color-border-hover: {c.border_hover};
    --radius-sm: {ra.sm};
    --radius-md: {ra.md};
    --radius-lg: {ra.lg};
    --radius-pill: {ra.pill};
    --shadow-focus: {sh.focus};
  }}

  /* ── Base ─────────────────────────────────────────────────────────── */
  html, body, [class*="css"] {{
    font-family: {ty.family_sans} !important;
  }}
  .block-container {{
    padding-top: calc({la.container_padding_top} * var(--density));
    padding-bottom: {la.container_padding_bottom};
    max-width: {la.container_max_width};
  }}
  h1, h2, h3, h4 {{
    font-weight: {ty.weight_semibold} !important;
    letter-spacing: {ty.letter_tight};
    font-family: 'Inter', sans-serif !important;
    color: {c.text_primary} !important;
  }}
  h1 {{ font-size: {ty.size_xl} !important; }}
  h2 {{ font-size: {ty.size_lg} !important; color: {c.text_secondary} !important; }}
  h3 {{ font-size: {ty.size_md} !important; }}
  h4 {{ font-size: {ty.size_sm} !important; color: {c.text_secondary} !important; }}

  /* ── Hide Streamlit chrome para look "producto" ───────────────────── */
  /* Oculta hamburguesa, "Made with Streamlit", botón Deploy, navegación
     multipage nativa y header superior. La app provee su propio header. */
  #MainMenu {{ visibility: hidden !important; }}
  header[data-testid="stHeader"] {{
    background: transparent !important;
  }}
  /* Oculta toolbar (deploy, menú) pero mantiene el botón de expandir sidebar */
  [data-testid="stToolbar"] {{ visibility: hidden !important; }}
  [data-testid="stExpandSidebarButton"] {{
    visibility: visible !important;
    display: block !important;
    position: fixed !important;
    top: 50% !important;
    left: 0 !important;
    transform: translateY(-50%) !important;
    z-index: 999 !important;
    background: {c.bg_elev_1} !important;
    backdrop-filter: blur(12px) !important; -webkit-backdrop-filter: blur(12px) !important;
    border: 1px solid {c.border_subtle} !important;
    border-left: none !important;
    border-radius: 0 {ra.sm} {ra.sm} 0 !important;
    padding: 12px 8px !important;
    box-shadow: 2px 0 12px rgba(0,0,0,0.2) !important;
    transition: background 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease !important;
  }}
  [data-testid="stExpandSidebarButton"]:hover {{
    background: rgba(0,163,224,0.08) !important;
    border-color: {c.accent_primary} !important;
    box-shadow: 2px 0 16px rgba(0,163,224,0.15) !important;
  }}
  [data-testid="stExpandSidebarButton"] svg {{
    color: {c.accent_primary} !important;
    width: 18px !important;
    height: 18px !important;
  }}
  [data-testid="stAppDeployButton"] {{ display: none !important; }}
  [data-testid="stMainMenu"] {{ display: none !important; }}
  footer {{ visibility: hidden !important; height: 0 !important; }}
  div[data-testid="stDecoration"] {{ display: none !important; }}
  div[data-testid="stStatusWidget"] {{ display: none !important; }}
  [data-testid="stSidebarNav"] {{ display: none !important; }}
  [data-testid="stSidebarNavSeparator"] {{ display: none !important; }}
  /* "Made with Streamlit" en builds nuevos */
  a[href*="streamlit.io"][target="_blank"] {{ display: none !important; }}

  /* ── Sidebar ──────────────────────────────────────────────────────── */
  section[data-testid="stSidebar"] {{
    width: {la.sidebar_width} !important;
    min-width: {la.sidebar_width} !important;
    max-width: {la.sidebar_width} !important;
    background: linear-gradient(180deg, {c.bg_sidebar_top} 0%, {c.bg_sidebar_bottom} 100%) !important;
    border-right: 1px solid {c.border_subtle} !important;
    box-shadow: 4px 0 24px -4px rgba(0,0,0,0.3);
  }}
  section[data-testid="stSidebar"] > div {{ padding-top: {t.spacing.lg}; }}

  /* ── Sidebar collapsed: contenido ocupa ancho completo ────────────── */
  section[data-testid="stSidebar"][aria-expanded="false"] {{
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    overflow: hidden !important;
  }}
  section[data-testid="stSidebar"][aria-expanded="false"] ~ section[data-testid="stMain"] .block-container,
  [data-testid="stAppViewBlockContainer"] {{
    max-width: 100% !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
    transition: max-width 0.3s ease, padding 0.3s ease;
  }}
  /* Transición suave al abrir/cerrar sidebar */
  section[data-testid="stSidebar"] {{
    transition: width 0.3s ease, min-width 0.3s ease, max-width 0.3s ease !important;
  }}
  .block-container {{
    transition: max-width 0.3s ease, padding 0.3s ease !important;
  }}

  /* ── Layout: column gap & vertical alignment ─────────────────────── */
  /* Asegura que todas las columnas de un mismo bloque horizontal tengan la
     misma altura (cards alineadas) y un gap uniforme entre ellas. */
  [data-testid="stHorizontalBlock"] {{
    gap: calc(14px * var(--density)) !important;
    align-items: stretch !important;
  }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
    display: flex;
    flex-direction: column;
  }}
  /* Que los hijos directos (markdown con la card) ocupen toda la altura */
  [data-testid="stHorizontalBlock"] > [data-testid="column"] > div {{
    height: 100%;
  }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"] [data-testid="stMarkdownContainer"] {{
    height: 100%;
  }}

  /* Espaciado consistente de cabeceras de sección dentro de la página */
  .block-container h2 {{ margin-top: calc(28px * var(--density)) !important; margin-bottom: calc(10px * var(--density)) !important; }}
  .block-container h3 {{ margin-top: calc(20px * var(--density)) !important; margin-bottom: calc(6px * var(--density)) !important; }}
  .block-container h4 {{ margin-top: calc(14px * var(--density)) !important; margin-bottom: calc(4px * var(--density)) !important; }}

  /* Margen inferior consistente para gráficos Plotly */
  [data-testid="stPlotlyChart"] {{ margin-bottom: calc(8px * var(--density)); }}

  /* ── App header (3-zonas: brand · meta · acciones) ───────────────── */
  .app-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: {t.spacing.md};
    padding-bottom: calc(14px * var(--density));
    margin-bottom: calc(18px * var(--density));
    border-bottom: 1px solid {c.border_subtle};
  }}
  .app-header .ah-title {{
    font-size: {ty.size_xl};
    font-weight: {ty.weight_bold};
    letter-spacing: {ty.letter_tight};
    color: {c.text_primary};
    margin: 0;
    line-height: 1.2;
    background: linear-gradient(135deg, {c.text_primary} 0%, {c.accent_secondary} 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }}
  .app-header .ah-subtitle {{
    font-size: {ty.size_xs};
    color: {c.text_muted};
    text-transform: uppercase;
    letter-spacing: {ty.letter_kpi_label};
    margin-top: 2px;
  }}
  .app-header .ah-meta {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: {ty.size_xs};
    color: {c.text_muted};
    background: {c.bg_elev_1};
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
    border: 1px solid {c.border_subtle};
    padding: 5px 12px;
    border-radius: {ra.pill};
    white-space: nowrap;
    box-shadow: 0 1px 4px rgba(0,0,0,0.1);
  }}
  .app-header .ah-meta svg {{ flex-shrink: 0; opacity: 0.85; }}

  /* ── Brand del sidebar ────────────────────────────────────────────── */
  .brand {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 4px 4px 0 4px;
    margin-bottom: calc(18px * var(--density));
  }}
  .brand .brand-logo {{ flex-shrink: 0; line-height: 0; }}
  .brand .brand-text {{ display: flex; flex-direction: column; line-height: 1.15; }}
  .brand .brand-name {{
    font-size: 1rem;
    font-weight: {ty.weight_bold};
    color: {c.text_primary};
    letter-spacing: -0.015em;
    background: linear-gradient(135deg, {c.text_primary}, {c.accent_primary});
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }}
  .brand .brand-tag {{
    font-size: 0.66rem;
    color: {c.text_muted};
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 1px;
  }}

  /* ── Filtros: agrupación visual en sidebar ────────────────────────── */
  .filter-group-header {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 0.7rem;
    color: {c.text_muted};
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: {ty.weight_semibold};
    margin: calc(14px * var(--density)) 0 calc(6px * var(--density)) 0;
  }}
  .filter-group-header svg {{ opacity: 0.75; }}

  /* ── Chips de filtros activos (sin st.columns) ───────────────────── */
  .chip-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin: 4px 0 2px 0;
  }}
  .filter-chip {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: {c.bg_elev_1};
    border: 1px solid {c.border_subtle};
    border-radius: {ra.pill};
    padding: 3px 11px;
    font-size: 0.76rem;
    color: {c.text_card_title};
    white-space: nowrap;
    line-height: 1.4;
    transition: border-color 0.15s, background 0.15s;
  }}
  .filter-chip:hover {{
    border-color: {c.accent_primary};
    background: rgba(0,163,224,0.08);
  }}
  .filter-chip svg {{ opacity: 0.7; flex-shrink: 0; }}

  /* ── KPI Cards ────────────────────────────────────────────────────── */
  .kpi-card {{
    background: {c.bg_elev_1};
    backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
    border: 1px solid {c.border_subtle};
    border-radius: {ra.md};
    padding: calc(18px * var(--density)) calc(22px * var(--density));
    box-shadow: {sh.md};
    transition: border-color 0.2s, transform 0.15s, box-shadow 0.2s;
    /* Layout interno consistente: label arriba, value medio, delta abajo. */
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: 100%;
    min-height: calc(118px * var(--density));
    position: relative;
    overflow: hidden;
  }}
  .kpi-card:hover {{
    border-color: {c.accent_primary};
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,163,224,0.12), 0 2px 8px rgba(0,0,0,0.2);
  }}
  .kpi-card .label {{
    color: {c.text_muted}; font-size: {ty.size_xs}; font-weight: {ty.weight_medium};
    text-transform: uppercase; letter-spacing: {ty.letter_kpi_label};
    margin-bottom: calc(6px * var(--density));
    /* Truncar a 2 líneas para evitar saltos de altura entre cards. */
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 1.8em;
  }}
  .kpi-card .value {{
    color: {c.text_value};
    font-size: calc({ty.size_2xl} * var(--density));
    font-weight: {ty.weight_bold};
    line-height: 1.1; letter-spacing: -0.02em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .kpi-card .delta {{
    font-size: 0.76rem;
    margin-top: calc(6px * var(--density));
    font-weight: {ty.weight_medium};
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-height: 1.05em;
  }}
  .kpi-card .delta.up {{ color: {c.success}; }}
  .kpi-card .delta.down {{ color: {c.danger}; }}
  .kpi-card .icon {{
    color: {c.accent_primary}; opacity: 0.55;
    position: absolute; top: calc(14px * var(--density)); right: calc(16px * var(--density));
    line-height: 0;
  }}
  .kpi-card .icon svg {{ width: 18px; height: 18px; }}
  .kpi-card .sparkline-wrap {{ margin-top: calc(4px * var(--density)); min-height: 24px; }}
  .kpi-card .anomaly-badge {{
    position: absolute; top: calc(14px * var(--density)); right: calc(44px * var(--density));
    font-size: 0.85rem; color: {c.danger};
  }}

  /* ── Top cards ────────────────────────────────────────────────────── */
  .top-card {{
    background: {c.bg_elev_2};
    border: 1px solid {c.border_card};
    border-left: 3px solid {c.accent_primary};
    border-radius: {ra.md};
    padding: calc(14px * var(--density)) calc(18px * var(--density));
    margin-bottom: calc(10px * var(--density));
    transition: border-color 0.15s, transform 0.15s;
    /* Altura mínima para que un listado de top-cards tenga ritmo visual. */
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: calc(96px * var(--density));
  }}
  .top-card:hover {{
    border-color: {c.border_hover};
    border-left-color: {c.accent_primary_hover};
    transform: translateX(1px);
  }}
  .top-card .amount {{
    font-size: calc(1.25rem * var(--density));
    font-weight: {ty.weight_bold};
    color: {c.accent_primary};
    letter-spacing: -0.01em;
  }}
  .top-card .title {{
    font-size: 0.88rem; color: {c.text_card_title}; margin: 4px 0; line-height: 1.35;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }}
  .top-card .title a {{ color: {c.text_card_title}; text-decoration: none; }}
  .top-card .title a:hover {{ color: {c.accent_primary}; }}
  .top-card .meta {{
    font-size: 0.74rem; color: {c.text_muted};
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
  .bc-section {{ color: {c.text_muted}; font-weight: {ty.weight_medium}; }}
  .bc-sep {{ color: {c.text_disabled}; display: inline-flex; line-height: 0; }}
  .bc-page {{ color: {c.accent_primary}; font-weight: {ty.weight_medium}; }}

  /* ── Empty / error states ─────────────────────────────────────────── */
  .empty-state {{
    text-align: center;
    padding: 2.5rem 1rem 1.5rem;
  }}
  .empty-state .es-icon {{
    color: {c.text_muted};
    margin-bottom: 0.75rem;
    line-height: 0;
    display: flex;
    justify-content: center;
  }}
  .empty-state .es-icon svg {{ width: 44px; height: 44px; }}
  .empty-state .es-title {{
    font-size: 1rem;
    font-weight: {ty.weight_semibold};
    color: {c.text_card_title};
    margin-bottom: 0.35rem;
  }}
  .empty-state .es-msg {{
    font-size: 0.85rem;
    color: {c.text_muted};
    max-width: 380px;
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
  .error-banner svg {{ color: {c.danger}; flex-shrink: 0; margin-top: 2px; }}
  .error-banner strong {{ color: {c.text_value}; display: block; margin-bottom: 2px; }}
  .error-banner span {{ color: {c.text_muted}; font-size: 0.875rem; }}

  /* ── Metrics & misc ───────────────────────────────────────────────── */
  div[data-testid="stMetricValue"] {{ font-size: 1.5rem; }}
  .stDivider {{ opacity: 0.3; }}
  ::-webkit-scrollbar {{ width: 5px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: {c.scrollbar_thumb}; border-radius: 3px; }}

  /* ── Density: tablas (Aggrid / dataframe) ─────────────────────────── */
  .ag-theme-streamlit .ag-row, .ag-theme-balham-dark .ag-row {{
    height: calc(34px * var(--density)) !important;
    min-height: calc(34px * var(--density)) !important;
  }}

  /* ── Focus visible (accesibilidad) ────────────────────────────────── */
  button:focus-visible,
  a:focus-visible,
  input:focus-visible,
  select:focus-visible,
  [role="button"]:focus-visible,
  .filter-chip:focus-visible,
  .kpi-card:focus-visible,
  .top-card:focus-visible {{
    outline: none !important;
    box-shadow: {sh.focus} !important;
  }}

  /* ── Loading skeleton shimmer ─────────────────────────────────────── */
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

  /* ── Responsive — tablet (≤ {bp.tablet_max}px) ───────────────────── */
  @media (max-width: {bp.tablet_max}px) {{
    .block-container {{
      max-width: 100% !important;
      padding-left: 1rem !important;
      padding-right: 1rem !important;
    }}
    section[data-testid="stSidebar"] {{
      width: 220px !important;
      min-width: 220px !important;
      max-width: 220px !important;
    }}
    .kpi-card {{ padding: 14px 16px; }}
    .kpi-card .value {{ font-size: 1.4rem; }}
    /* Wrap KPI columns: mínimo 48% para que quepan de 2 en 2 */
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
      min-width: 48% !important;
    }}
  }}

  /* ── Responsive — mobile (≤ {bp.mobile_max}px) ───────────────────── */
  @media (max-width: {bp.mobile_max}px) {{
    .block-container {{
      padding-left: 0.5rem !important;
      padding-right: 0.5rem !important;
    }}
    /* Stack vertical: cada columna ocupa 100% */
    [data-testid="stHorizontalBlock"] {{
      flex-wrap: wrap !important;
    }}
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
      flex: 1 1 100% !important;
      min-width: 100% !important;
    }}
    /* Reducir altura mínima de KPI en mobile para evitar huecos. */
    .kpi-card {{ min-height: auto; }}
    .app-header {{ flex-direction: column; align-items: flex-start; gap: 8px; }}
  }}

  /* ── Skip-link (accesibilidad) ────────────────────────────────────── */
  .skip-link {{
    position: absolute;
    left: -9999px;
    top: auto;
    width: 1px;
    height: 1px;
    overflow: hidden;
    z-index: 9999;
    padding: 0.75rem 1.5rem;
    background: {c.accent_primary};
    color: {c.bg_base};
    font-weight: {ty.weight_semibold};
    border-radius: {ra.sm};
    text-decoration: none;
  }}
  .skip-link:focus {{
    left: 1rem;
    top: 0.5rem;
    width: auto;
    height: auto;
    overflow: visible;
  }}

  /* ── prefers-reduced-motion ───────────────────────────────────────── */
  @media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
      animation-duration: 0.001s !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.001s !important;
    }}
  }}

  /* ── Status badges ────────────────────────────────────────────────── */
  .status-badge {{
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 10px;
    border-radius: {ra.pill};
    font-size: 0.75rem;
    font-weight: {ty.weight_medium};
    border: 1px solid transparent;
    line-height: 1.5;
    white-space: nowrap;
    color: var(--badge-color, {c.text_muted});
    background: color-mix(in srgb, var(--badge-color, {c.text_muted}) 12%, transparent);
    border-color: color-mix(in srgb, var(--badge-color, {c.text_muted}) 30%, transparent);
    transition: opacity 0.15s ease;
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
    background: {c.bg_hoverlabel};
    color: {c.text_primary};
    border: 1px solid {c.border_hoverlabel};
    border-radius: {ra.sm};
    padding: 5px 10px;
    font-size: 0.75rem;
    white-space: nowrap;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.15s ease;
    z-index: 200;
    box-shadow: {sh.md};
  }}
  .has-tooltip:hover::after {{ opacity: 1; }}

  /* ── Search highlight ─────────────────────────────────────────────── */
  mark.search-hl {{
    background: rgba(0,163,224,0.25);
    color: inherit;
    padding: 1px 2px;
    border-radius: 3px;
    font-style: normal;
    font-weight: {ty.weight_medium};
  }}

  /* ── Skeleton shapes para KPI y top-card ─────────────────────────── */
  .skeleton-card {{
    /* Reutiliza la animación shimmer del .skeleton, sin height fija */
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

  /* ── Sticky headers en tablas nativas ────────────────────────────── */
  .stDataFrame thead th {{
    position: sticky;
    top: 0;
    z-index: 1;
    background: {c.bg_base};
  }}

  /* ── Premium: Staggered card entrance ──────────────────────────────── */
  @keyframes cardFadeUp {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
  @keyframes glowPulse {{
    0%, 100% {{ opacity: 0; }}
    50% {{ opacity: 1; }}
  }}
  @keyframes countUp {{
    from {{ opacity: 0; transform: translateY(4px); filter: blur(2px); }}
    to   {{ opacity: 1; transform: translateY(0); filter: blur(0); }}
  }}

  /* Stagger entrance for KPI cards */
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(1) .kpi-card {{ animation: cardFadeUp 0.4s cubic-bezier(0.22,1,0.36,1) 0.05s both; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(2) .kpi-card {{ animation: cardFadeUp 0.4s cubic-bezier(0.22,1,0.36,1) 0.12s both; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(3) .kpi-card {{ animation: cardFadeUp 0.4s cubic-bezier(0.22,1,0.36,1) 0.19s both; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(4) .kpi-card {{ animation: cardFadeUp 0.4s cubic-bezier(0.22,1,0.36,1) 0.26s both; }}
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(5) .kpi-card {{ animation: cardFadeUp 0.4s cubic-bezier(0.22,1,0.36,1) 0.33s both; }}

  /* Stagger entrance for top-cards */
  .top-card:nth-child(1) {{ animation: cardFadeUp 0.35s cubic-bezier(0.22,1,0.36,1) 0.08s both; }}
  .top-card:nth-child(2) {{ animation: cardFadeUp 0.35s cubic-bezier(0.22,1,0.36,1) 0.16s both; }}
  .top-card:nth-child(3) {{ animation: cardFadeUp 0.35s cubic-bezier(0.22,1,0.36,1) 0.24s both; }}
  .top-card:nth-child(4) {{ animation: cardFadeUp 0.35s cubic-bezier(0.22,1,0.36,1) 0.32s both; }}
  .top-card:nth-child(5) {{ animation: cardFadeUp 0.35s cubic-bezier(0.22,1,0.36,1) 0.40s both; }}

  /* Number count-up feel for KPI values */
  .kpi-card .value {{ animation: countUp 0.5s cubic-bezier(0.22,1,0.36,1) 0.3s both; }}

  /* ── Premium: Gradient glow on KPI cards ──────────────────────────── */
  .kpi-card::before {{
    content: "";
    position: absolute;
    inset: -1px;
    border-radius: {ra.md};
    padding: 1px;
    background: linear-gradient(135deg, rgba(0,163,224,0.15), rgba(91,192,235,0.05), transparent 60%);
    -webkit-mask: linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite: xor;
    mask-composite: exclude;
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.3s ease;
  }}
  .kpi-card:hover::before {{ opacity: 1; }}

  /* ── Premium: Enhanced hover glow ─────────────────────────────────── */
  .kpi-card::after {{
    content: "";
    position: absolute;
    top: 50%; left: 50%;
    width: 120%; height: 120%;
    transform: translate(-50%, -50%);
    background: radial-gradient(ellipse at center, rgba(0,163,224,0.06) 0%, transparent 70%);
    pointer-events: none;
    opacity: 0;
    transition: opacity 0.3s ease;
  }}
  .kpi-card:hover::after {{ opacity: 1; }}

  /* ── Premium: Subtle page background texture ──────────────────────── */
  .block-container::before {{
    content: "";
    position: fixed;
    inset: 0;
    background:
      radial-gradient(ellipse at 20% 0%, rgba(0,163,224,0.03) 0%, transparent 50%),
      radial-gradient(ellipse at 80% 100%, rgba(91,192,235,0.02) 0%, transparent 50%);
    pointer-events: none;
    z-index: -1;
  }}

  /* ── Premium: Top card gradient accent ────────────────────────────── */
  .top-card {{
    border-left: none !important;
    border-image: linear-gradient(180deg, {c.accent_primary}, {c.accent_secondary}) 1;
    border-left-width: 3px !important;
    border-left-style: solid !important;
  }}
  .top-card:hover {{
    box-shadow: -4px 0 16px -4px rgba(0,163,224,0.15), 0 4px 12px rgba(0,0,0,0.1);
  }}

  /* ── Premium: Navigation tabs ─────────────────────────────────────── */
  .top-nav-wrap div[role="radiogroup"] > label:has(input:checked)::after {{
    content: "";
    position: absolute;
    bottom: -7px; left: 20%; right: 20%;
    height: 2px;
    background: linear-gradient(90deg, {c.accent_primary}, {c.accent_secondary});
    border-radius: 2px;
  }}
  .top-nav-wrap div[role="radiogroup"] > label {{
    position: relative;
  }}

  /* ── Premium: Chart container styling ─────────────────────────────── */
  [data-testid="stPlotlyChart"] > div {{
    border-radius: {ra.md};
    border: none;
    background: transparent;
    padding: 8px;
  }}

  /* ── Premium: Sidebar separator glow ──────────────────────────────── */
  section[data-testid="stSidebar"] .stDivider {{
    background: linear-gradient(90deg, transparent, {c.border_subtle}, transparent) !important;
    height: 1px !important;
    border: none !important;
    opacity: 1 !important;
  }}

  /* ── Premium: Brand logo glow ─────────────────────────────────────── */
  .brand .brand-logo svg {{
    filter: drop-shadow(0 0 6px rgba(0,163,224,0.3));
  }}

  /* ── Micro-interacciones (respeta prefers-reduced-motion) ─────────── */
  @media (prefers-reduced-motion: no-preference) {{
    .filter-chip {{ transition: border-color 0.15s ease, background 0.15s ease, transform 0.1s ease; }}
    .filter-chip:hover {{ transform: translateY(-1px); }}
    .status-badge {{ transition: opacity 0.15s ease, transform 0.1s ease; }}
    .error-banner {{ animation: fadeInDown 0.2s ease; }}
    @keyframes fadeInDown {{
      from {{ opacity: 0; transform: translateY(-6px); }}
      to   {{ opacity: 1; transform: translateY(0); }}
    }}
  }}

  /* ── Responsive — iPad portrait (≤ {bp.tablet_mid}px) ───────────── */
  @media (max-width: {bp.tablet_mid}px) {{
    /* Stack KPI completo en iPad portrait */
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
      flex: 1 1 100% !important;
      min-width: 100% !important;
    }}
    /* Reducir altura mínima de charts en pantalla estrecha */
    [data-testid="stPlotlyChart"] {{ min-height: 280px; }}
  }}

  /* ── Mobile scroll indicator en tablas ───────────────────────────── */
  @media (max-width: {bp.mobile_max}px) {{
    .stDataFrame {{
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }}
    /* Gradient derecho como indicador visual de scroll */
    [data-testid="stDataFrame"] {{
      position: relative;
    }}
    [data-testid="stDataFrame"]::after {{
      content: "";
      position: absolute;
      top: 0; right: 0; bottom: 0;
      width: 32px;
      background: linear-gradient(to right, transparent, {c.bg_base});
      pointer-events: none;
    }}
  }}
</style>
"""
