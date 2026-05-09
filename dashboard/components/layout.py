"""Componentes de layout — topbar unificada, footer y branding.

Premium refresh: el header tradicional + top-nav se unifican en una sola
``topbar`` fija (logo · nav slot · meta pill · acciones). El logo ya no
está en el sidebar, lo que libera espacio para los filtros.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from dashboard.components.icons import LOGO_SVG, icon
from dashboard.data_loader import load_extracciones


def _format_last_updated(ts) -> str:
    """Devuelve un texto humano corto para la pill de 'Última actualización'."""
    if ts is None:
        return "sin datos"
    if isinstance(ts, str):
        ts = pd.to_datetime(ts, utc=True, errors="coerce")
    if pd.isna(ts):
        return "sin datos"
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        ts = ts.tz_localize("UTC")

    now = datetime.now(UTC)
    delta = now - (ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts)
    secs = int(delta.total_seconds())
    if secs < 60:
        return "hace segundos"
    if secs < 3600:
        return f"hace {secs // 60} min"
    if secs < 86400:
        return f"hace {secs // 3600} h"
    days = secs // 86400
    return f"hace {days} d" if days < 30 else ts.strftime("%Y-%m-%d")


def render_topbar_brand(tagline: str = "Sector público · ES") -> None:
    """Renderiza el bloque brand del topbar (logo + nombre + tagline)."""
    st.markdown(
        f'<div class="topbar-brand">'
        f'<span class="brand-logo">{LOGO_SVG}</span>'
        f'<span class="brand-name">Licitaciones SAP</span>'
        f'<span class="brand-tag">{tagline}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_topbar(last_updated=None) -> bool:
    """Topbar premium: brand + meta pill + acciones (refresh, theme toggle).

    Devuelve el estado del toggle de tema (False = dark, True = light) para
    que el caller inyecte el atributo ``data-theme`` correspondiente.

    Layout: usa st.columns con anchos relativos para alinear los slots.
    """
    last_str = _format_last_updated(last_updated)

    # Apertura del wrapper visual de la topbar
    st.markdown('<div class="topbar">', unsafe_allow_html=True)

    col_brand, col_spacer, col_meta, col_theme, col_refresh = st.columns(
        [3, 6, 2.2, 0.6, 0.6], gap="small", vertical_alignment="center"
    )
    with col_brand:
        render_topbar_brand()
    with col_spacer:
        st.markdown('<div class="topbar-spacer"></div>', unsafe_allow_html=True)
    with col_meta:
        st.markdown(
            '<div style="display:flex;justify-content:flex-end;align-items:center;height:100%">'
            '<span class="topbar-meta">'
            '<span class="pulse-dot"></span>'
            f"{icon('clock', 12)} Actualizado {last_str}"
            "</span></div>",
            unsafe_allow_html=True,
        )
    with col_theme:
        # Toggle dark/light. Persistido en session_state.
        light = st.toggle(
            "☀",
            key="ui_light_mode",
            value=st.session_state.get("ui_light_mode", False),
            help="Cambiar a tema claro / oscuro",
            label_visibility="collapsed",
        )
    with col_refresh:
        if st.button(
            "↻",
            use_container_width=True,
            help="Refrescar caché de datos",
            key="header_refresh",
        ):
            st.cache_data.clear()
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)
    return bool(light)


# ── Backward-compat shims ────────────────────────────────────────────────


def render_header(
    title: str = "Licitaciones SAP",
    subtitle: str | None = "Inteligencia comercial · Sector público",
    last_updated=None,
) -> None:
    """Compat: delega a render_topbar (el header clásico ya no se usa)."""
    _ = (title, subtitle)  # silencia args legacy
    render_topbar(last_updated=last_updated)


def render_sidebar_brand() -> None:
    """Compat: en el nuevo layout el brand vive en la topbar.

    Mantenida para no romper imports externos. Renderiza un divisor sutil
    con un caption fino para empezar el sidebar de forma limpia.
    """
    st.markdown(
        '<div style="height:6px"></div>',
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    """Footer con metadatos de última extracción y atribución de fuente."""
    st.divider()
    ext = load_extracciones()
    if not ext.empty:
        st.markdown(
            f'<div style="font-size:0.78rem;color:var(--color-text-muted);'
            f'display:flex;align-items:center;gap:6px">'
            f"{icon('database', 12)}"
            f"<span>Última extracción: {ext.iloc[0]['fecha']} — fuente "
            f"{ext.iloc[0]['fuente']} ({ext.iloc[0]['nuevas']} nuevas)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
    st.caption(
        "Fuente oficial: contrataciondelestado.es · Datos reutilizados al amparo de la Ley 37/2007"
    )
