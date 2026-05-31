"""CSS de componentes UI: KPI cards, top cards, filtros, tablas, estados, etc."""

from __future__ import annotations

from dashboard.theme.tokens import Tokens


def build_components_css(t: Tokens) -> str:
    c = t.colors
    ty = t.type
    ra = t.radii
    return f"""
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
    padding: 7px 13px;
    min-height: 36px;  /* touch-target: comfortable ≥36px visual height */
    font-size: 0.74rem;
    color: var(--color-text-card-title);
    white-space: nowrap;
    line-height: 1.4;
    transition: border-color 150ms cubic-bezier(0.16,1,0.3,1),
                background 150ms ease,
                transform 150ms cubic-bezier(0.16,1,0.3,1),
                box-shadow 150ms ease;
  }}
  .filter-chip:hover {{
    border-color: rgba(134,188,36,0.50);
    background: rgba(134,188,36,0.08);
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(134,188,36,0.14);
  }}
  .filter-chip svg {{ opacity: 0.7; flex-shrink: 0; }}

  /* ── KPI Cards (sólidos con gradient interior + sombra 2 capas) ─── */
  .kpi-card {{
    background: var(--color-bg-elev-1);
    background-image: linear-gradient(180deg, rgba(255,255,255,0.028) 0%, rgba(255,255,255,0) 60%);
    border: 1px solid var(--color-border-card);
    border-radius: {ra.md};
    padding: calc(18px * var(--density)) calc(20px * var(--density));
    transition: border-color 200ms cubic-bezier(0.16,1,0.3,1),
                transform 200ms cubic-bezier(0.16,1,0.3,1),
                box-shadow 200ms cubic-bezier(0.16,1,0.3,1);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    height: 100%;
    min-height: calc(122px * var(--density));
    position: relative;
    overflow: hidden;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), var(--shadow-sm);
  }}
  .kpi-card:hover {{
    border-color: rgba(134,188,36,0.38);
    transform: translateY(-3px);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.08),
                0 12px 30px -8px rgba(0,0,0,0.60),
                0 2px 8px rgba(134,188,36,0.12);
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
    font-weight: {ty.weight_semibold};
    line-height: 1.1;
    letter-spacing: {ty.letter_display};
    font-variant-numeric: var(--tab-numerals);
    font-feature-settings: var(--font-feature), "tnum";
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    background: linear-gradient(180deg, #FFFFFF 0%, rgba(255,255,255,0.72) 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
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
    background-image: linear-gradient(180deg, rgba(255,255,255,0.022) 0%, rgba(255,255,255,0) 60%);
    border: 1px solid var(--color-border-card);
    border-left: 3px solid var(--color-accent-primary);
    border-radius: {ra.md};
    padding: calc(14px * var(--density)) calc(18px * var(--density));
    margin-bottom: calc(10px * var(--density));
    transition: border-color 200ms cubic-bezier(0.16,1,0.3,1),
                transform 200ms cubic-bezier(0.16,1,0.3,1),
                box-shadow 200ms cubic-bezier(0.16,1,0.3,1);
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: calc(96px * var(--density));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.04), var(--shadow-sm);
  }}
  .top-card:hover {{
    border-color: rgba(134,188,36,0.35);
    transform: translateX(3px);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06),
                -3px 0 16px -4px rgba(134,188,36,0.22),
                0 6px 18px rgba(0,0,0,0.28);
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

  /* ── Pagination info bar ─────────────────────────────────────────── */
  .pagination-info {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 4px 0;
  }}
  .pagination-range {{
    font-size: 0.8rem;
    color: var(--color-text-secondary);
    font-variant-numeric: var(--tab-numerals);
    font-weight: {ty.weight_medium};
  }}
  .pagination-sep {{
    color: var(--color-border-subtle);
    font-size: 0.75rem;
  }}
  .pagination-page {{
    font-size: 0.75rem;
    color: var(--color-text-muted);
    font-weight: {ty.weight_medium};
  }}

  /* ── Empty / error states ─────────────────────────────────────────── */
  .empty-state {{
    text-align: center;
    padding: 3rem 1rem 2rem;
    max-width: 420px;
    margin: 0 auto;
  }}
  .empty-state .es-icon {{
    color: var(--color-text-muted);
    margin-bottom: 1rem;
    line-height: 0;
    display: flex; justify-content: center;
    animation: cardFadeUp 0.40s cubic-bezier(0.22,1,0.36,1) both;
  }}
  .empty-state .es-icon svg {{
    width: 96px; height: 96px; opacity: 1;
    filter: drop-shadow(0 4px 24px rgba(134,188,36,0.12));
  }}
  .empty-state .es-icon svg[width="44"] {{
    width: 44px; height: 44px; opacity: 0.6;
    filter: none;
  }}
  .empty-state .es-title {{
    font-family: {ty.family_display};
    font-size: 1.1rem;
    font-weight: {ty.weight_semibold};
    color: var(--color-text-card-title);
    margin-bottom: 0.4rem;
    letter-spacing: {ty.letter_tight};
  }}
  .empty-state .es-msg {{
    font-size: 0.875rem;
    color: var(--color-text-muted);
    max-width: 360px;
    margin: 0 auto;
    line-height: 1.55;
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

  /* ── Chart cards (`:has` gives (0,2,0) — no !important needed) ────── */
  [data-testid="stVerticalBlockBorderWrapper"]:has(.chart-card-header) {{
    background: var(--color-bg-elev-1);
    background-image: linear-gradient(180deg, rgba(255,255,255,0.018), rgba(255,255,255,0));
    border: 1px solid var(--color-border-card);
    border-radius: {ra.md};
    box-shadow: var(--shadow-sm);
    transition: border-color 0.2s, box-shadow 0.2s;
  }}
  [data-testid="stVerticalBlockBorderWrapper"]:has(.chart-card-header):hover {{
    border-color: var(--color-border-hover);
    box-shadow: 0 4px 18px -6px rgba(134,188,36,0.10), var(--shadow-sm);
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
    );
    background-size: 600px 100%;
    animation: shimmer 1.4s ease-in-out infinite;
    border-color: transparent;
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

  /* ── Tablas nativas premium ──────────────────────────────────────── */
  .stDataFrame thead th {{
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--color-bg-elev-2);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-bottom: 1px solid var(--color-border-subtle) !important;
    font-weight: {ty.weight_semibold};
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.045em;
    color: var(--color-text-muted);
  }}
  .stDataFrame tbody tr:nth-child(even) {{ background: transparent !important; }}
  .stDataFrame tbody tr:nth-child(odd)  {{ background: transparent !important; }}
  .stDataFrame tbody tr:hover {{
    background: rgba(134,188,36,0.05) !important;
    transition: background 120ms ease;
  }}
  .stDataFrame tbody td {{
    font-size: 0.84rem;
    border-bottom: 1px solid var(--color-border-subtle);
    padding: calc(8px * var(--density)) calc(12px * var(--density));
    vertical-align: middle;
    color: var(--color-text-secondary);
  }}
  .stDataFrame tbody td[data-type="float"],
  .stDataFrame tbody td[data-type="int"] {{
    text-align: right;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum";
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
"""
