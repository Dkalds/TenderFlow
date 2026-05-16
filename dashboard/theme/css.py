"""Generador del bloque `<style>` inyectado en Streamlit.

Orquesta los submódulos del sistema de diseño:
  _base.py        — variables CSS, tipografía, chrome, sidebar, layout
  _light.py       — overrides [data-theme="light"]
  _topbar.py      — topbar fija, nav pills, sub-nav
  _components.py  — KPI cards, top cards, filtros, tablas, etc.
  _animations.py  — keyframes, stagger, orbs
  _responsive.py  — media queries, accesibilidad, botones, reduced-motion
"""

from __future__ import annotations

from dashboard.theme._animations import build_animations_css
from dashboard.theme._base import build_base_css
from dashboard.theme._components import build_components_css
from dashboard.theme._light import build_light_css
from dashboard.theme._responsive import build_responsive_css
from dashboard.theme._topbar import build_topbar_css
from dashboard.theme.tokens import TOKENS, Tokens

# Densidad compacta: reduce el coeficiente que escala paddings/gaps.
COMPACT_DENSITY_CSS = "<style>:root { --density: 0.78; }</style>"


def build_css(t: Tokens = TOKENS) -> str:
    """Construye el bloque ``<style>`` completo para inyectar en Streamlit."""
    parts = [
        "<style>",
        build_base_css(t),
        build_light_css(t),
        build_topbar_css(t),
        build_components_css(t),
        build_animations_css(t),
        build_responsive_css(t),
        "</style>",
    ]
    return "\n".join(parts)
