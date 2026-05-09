"""Componentes de layout — header global, footer y sidebar branding."""

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


def render_header(
    title: str = "Licitaciones SAP",
    subtitle: str | None = "Inteligencia comercial · Sector público",
    last_updated=None,
) -> None:
    """Header pro de la app: título + pill 'última actualización' + refresh.

    Layout en 3 zonas: brand+título, meta (pill), acciones (botón refresh).
    """
    last_str = _format_last_updated(last_updated)
    sub_html = f'<div class="ah-subtitle">{subtitle}</div>' if subtitle else ""

    col_l, col_m, col_r = st.columns([6, 3, 1])
    with col_l:
        st.markdown(
            f'<div><h1 class="ah-title">{title}</h1>{sub_html}</div>',
            unsafe_allow_html=True,
        )
    with col_m:
        st.markdown(
            '<div style="display:flex;justify-content:flex-end;align-items:center;'
            'height:100%">'
            f'<span class="ah-meta">{icon("clock", 13)} '
            f"Actualizado {last_str}</span>"
            "</div>",
            unsafe_allow_html=True,
        )
    with col_r:
        if st.button(
            "↻",
            use_container_width=True,
            help="Refrescar caché de datos",
            key="header_refresh",
        ):
            st.cache_data.clear()
            st.rerun()

    st.markdown(
        '<div style="height:1px;'
        "background:linear-gradient(90deg, transparent, var(--color-accent-primary-hover), var(--color-border-subtle), transparent);"
        'margin:8px 0 18px 0;opacity:0.5"></div>',
        unsafe_allow_html=True,
    )


def render_sidebar_brand() -> None:
    """Logo + nombre + tagline en la parte superior del sidebar."""
    st.markdown(
        f'<div class="brand">'
        f'<div class="brand-logo">{LOGO_SVG}</div>'
        f'<div class="brand-text">'
        f'<span class="brand-name">Licitaciones SAP</span>'
        f'<span class="brand-tag">Sector público · ES</span>'
        f"</div></div>",
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
