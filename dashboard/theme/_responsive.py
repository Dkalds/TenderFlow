"""CSS responsive, accesibilidad, botones primarios y reduced-motion."""

from __future__ import annotations

from dashboard.theme.tokens import Tokens


def build_responsive_css(t: Tokens) -> str:
    ty = t.type
    ra = t.radii
    bp = t.breakpoints
    lc = t.light
    return f"""
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
    [data-testid="stExpander"] [data-testid="stHorizontalBlock"] {{
      flex-wrap: wrap !important;
    }}
    [data-testid="stExpander"] [data-testid="stHorizontalBlock"] > [data-testid="column"] {{
      flex: 1 1 100% !important;
      min-width: 100% !important;
    }}
    button[data-testid="stBaseButton-secondary"][kind="secondary"] {{
      font-size: 0.75rem !important;
      padding: 4px 8px !important;
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

  /* ── M13: Accessibility ───────────────────────────────────────────── */
  button:focus-visible,
  a:focus-visible,
  input:focus-visible,
  select:focus-visible,
  [role="button"]:focus-visible {{
    outline: 3px solid var(--color-accent-primary) !important;
    outline-offset: 2px !important;
  }}
  .topbar-meta, .stCaption, [data-testid="stCaption"] {{
    color: var(--color-text-muted) !important;
  }}

  /* ── M12: Feedback animations ─────────────────────────────────────── */
  @keyframes slideInRight {{
    from {{ transform: translateX(100%); opacity: 0; }}
    to {{ transform: translateX(0); opacity: 1; }}
  }}
  @keyframes fadeOut {{
    from {{ opacity: 1; }}
    to {{ opacity: 0; }}
  }}
  [data-testid="stToast"] {{
    animation: slideInRight 0.35s ease-out;
  }}
  button[kind="primary"]:active,
  button[kind="secondary"]:active {{
    transform: scale(0.97);
    transition: transform 0.1s ease;
  }}
  [data-testid="stExpander"] details[open] > div {{
    animation: cardFadeUp 0.25s ease-out;
  }}

  /* ── Botones primarios premium ────────────────────────────────────── */
  button[kind="primary"],
  [data-testid="stBaseButton-primary"] {{
    background: linear-gradient(180deg, #95CC2C 0%, #86BC24 100%) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.20),
                0 1px 3px rgba(0,0,0,0.25) !important;
    border: 1px solid rgba(134,188,36,0.5) !important;
    color: #0B0B0D !important;
    font-weight: {ty.weight_semibold} !important;
    letter-spacing: -0.01em !important;
    transition: transform 150ms cubic-bezier(0.16,1,0.3,1),
                box-shadow 150ms cubic-bezier(0.16,1,0.3,1),
                filter 150ms ease !important;
  }}
  button[kind="primary"]:hover,
  [data-testid="stBaseButton-primary"]:hover {{
    filter: brightness(1.08) !important;
    transform: translateY(-1px) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.22),
                0 4px 12px rgba(134,188,36,0.30) !important;
  }}
  button[kind="primary"]:active,
  [data-testid="stBaseButton-primary"]:active {{
    transform: translateY(0) !important;
    filter: brightness(0.96) !important;
  }}

  /* Light-mode overrides for primary button (restore green gradient) */
  [data-theme="light"] button[kind="primary"],
  [data-theme="light"] [data-testid="stBaseButton-primary"] {{
    background: linear-gradient(180deg, {lc.accent_secondary} 0%, {lc.accent_primary} 100%) !important;
    color: #FFFFFF !important;
    border: 1px solid {lc.accent_primary} !important;
  }}

  /* ── prefers-reduced-motion ───────────────────────────────────────── */
  @media (prefers-reduced-motion: reduce) {{
    *, *::before, *::after {{
      animation-duration: 0.001s !important;
      animation-iteration-count: 1 !important;
      transition-duration: 0.001s !important;
    }}
    .topbar-meta .pulse-dot {{ animation: none !important; }}
    /* Decorative backgrounds — remove, not just slow them */
    .block-container::before,
    .block-container::after {{ display: none !important; }}
    /* Named animations that don't get caught by the wildcard */
    [data-testid="stToast"] {{ animation: none !important; transition: none !important; }}
    .kpi-card, .top-card {{ transition: none !important; }}
    [data-testid="stExpander"] details[open] > div {{ animation: none !important; }}
    /* Chart entrance animations */
    [data-testid="stPlotlyChart"] {{ animation: none !important; }}
    /* Filter chips hover transform */
    .filter-chip {{ transition: none !important; transform: none !important; }}
  }}
"""
