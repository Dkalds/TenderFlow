"""CSS de la topbar fija, nav pills y sub-nav."""

from __future__ import annotations

from dashboard.theme.tokens import Tokens


def build_topbar_css(t: Tokens) -> str:
    ty = t.type
    ra = t.radii
    return f"""
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
    background: rgba(11,11,13,0.75);
    backdrop-filter: blur(18px) saturate(180%);
    -webkit-backdrop-filter: blur(18px) saturate(180%);
    border-bottom: 1px solid rgba(134,188,36,0.12);
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

  /* ── Top-nav pills (sección activa en topbar) ────────────────────── */
  .topbar-nav {{
    display: inline-flex;
    align-items: center;
    gap: 2px;
  }}
  .topbar-nav-item {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 14px;
    border-radius: {ra.pill};
    font-size: 0.82rem;
    font-weight: {ty.weight_medium};
    color: var(--color-text-muted);
    cursor: pointer;
    text-decoration: none;
    transition: color 150ms ease, background 150ms ease;
    white-space: nowrap;
  }}
  .topbar-nav-item:hover {{
    color: var(--color-text-primary);
    background: rgba(255,255,255,0.06);
  }}
  .topbar-nav-item.active {{
    color: var(--color-accent-primary);
    background: rgba(134,188,36,0.12);
    font-weight: {ty.weight_semibold};
  }}

  /* ── Sub-nav (pestañas dentro de página) ─────────────────────────── */
  .sub-nav {{
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--color-border-subtle);
    margin-bottom: 16px;
  }}
  .sub-nav-item {{
    padding: 8px 18px;
    font-size: 0.84rem;
    font-weight: {ty.weight_medium};
    color: var(--color-text-muted);
    cursor: pointer;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
    transition: color 150ms ease, border-color 150ms ease;
    white-space: nowrap;
  }}
  .sub-nav-item:hover {{
    color: var(--color-text-primary);
  }}
  .sub-nav-item.active {{
    color: var(--color-accent-primary);
    border-bottom-color: var(--color-accent-primary);
    font-weight: {ty.weight_semibold};
  }}
"""
