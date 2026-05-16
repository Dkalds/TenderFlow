"""CSS de animaciones y fondo decorativo."""

from __future__ import annotations

from dashboard.theme.tokens import Tokens


def build_animations_css(t: Tokens) -> str:
    return """
  /* ── Animaciones de entrada ───────────────────────────────────────── */
  @keyframes cardFadeUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes countUp {
    from { opacity: 0; transform: translateY(3px); filter: blur(1px); }
    to   { opacity: 1; transform: translateY(0); filter: blur(0); }
  }

  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(1) .kpi-card { animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.04s both; }
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(2) .kpi-card { animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.10s both; }
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(3) .kpi-card { animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.16s both; }
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(4) .kpi-card { animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.22s both; }
  [data-testid="stHorizontalBlock"] > [data-testid="column"]:nth-child(5) .kpi-card { animation: cardFadeUp 0.32s cubic-bezier(0.22,1,0.36,1) 0.28s both; }

  .top-card:nth-child(1) { animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.06s both; }
  .top-card:nth-child(2) { animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.12s both; }
  .top-card:nth-child(3) { animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.18s both; }
  .top-card:nth-child(4) { animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.24s both; }
  .top-card:nth-child(5) { animation: cardFadeUp 0.30s cubic-bezier(0.22,1,0.36,1) 0.30s both; }

  .kpi-card .value { animation: countUp 0.45s cubic-bezier(0.22,1,0.36,1) 0.25s both; }

  /* ── Subtle page background — gradient orbs + grain ──────────────── */
  .block-container::before {
    content: "";
    position: fixed;
    inset: 0;
    background:
      radial-gradient(ellipse 55% 38% at 14% -5%, rgba(134,188,36,0.055) 0%, transparent 55%),
      radial-gradient(ellipse 48% 36% at 86% 108%, rgba(134,188,36,0.038) 0%, transparent 55%);
    pointer-events: none;
    z-index: -1;
  }
  /* Grain noise sutil */
  .block-container::after {
    content: "";
    position: fixed;
    inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='200' height='200' filter='url(%23n)' opacity='0.04'/%3E%3C/svg%3E");
    background-size: 200px 200px;
    opacity: 0.45;
    pointer-events: none;
    z-index: -1;
  }
"""
