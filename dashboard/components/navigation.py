"""Componentes de navegación — breadcrumb, sub-nav y filtros activos."""

from __future__ import annotations

import html as _html
from collections.abc import Callable
from typing import TYPE_CHECKING

import streamlit as st

if TYPE_CHECKING:
    from dashboard.filters.state import FiltersState


def breadcrumb(section: str, page: str) -> None:
    """Renderiza `Sección › Página` en la barra de navegación secundaria."""
    safe_section = _html.escape(section)
    safe_page = _html.escape(page)
    st.markdown(
        f'<nav aria-label="breadcrumb">'
        f'<div class="bc">'
        f'<span class="bc-section">{safe_section}</span>'
        f'<span class="bc-sep" aria-hidden="true">›</span>'
        f'<span class="bc-page" aria-current="page">{safe_page}</span>'
        f"</div></nav>",
        unsafe_allow_html=True,
    )


def sub_nav(pages: list[str], *, key: str) -> str:
    """Radio horizontal para navegar entre sub-páginas de una sección."""
    return st.radio(
        "p",
        pages,
        horizontal=True,
        label_visibility="collapsed",
        key=key,
    )


def top_nav(
    sections: list[str],
    *,
    key: str,
    icons: dict[str, str] | None = None,
) -> str:
    """Barra de navegación principal horizontal (top-nav).

    Renderiza las secciones como radio horizontal estilizado a modo de
    pestañas/pills en la parte superior del contenido.
    """
    st.markdown(
        """
        <style>
          .top-nav-wrap { margin: 4px 0 10px 0; }
          div[data-testid="stRadio"]:has(> label[for*="topnav"]) > div[role="radiogroup"],
          .top-nav-wrap + div div[role="radiogroup"] {
            gap: 4px !important;
            flex-wrap: wrap;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            padding-bottom: 6px;
          }
          .top-nav-wrap + div div[role="radiogroup"] > label {
            background: transparent;
            border: 1px solid transparent;
            border-radius: 8px 8px 0 0;
            padding: 8px 14px !important;
            margin: 0 !important;
            transition: background .15s ease, color .15s ease;
            cursor: pointer;
            font-weight: 500;
          }
          .top-nav-wrap + div div[role="radiogroup"] > label:hover {
            background: rgba(255,255,255,0.05);
          }
          .top-nav-wrap + div div[role="radiogroup"] > label > div:first-child {
            display: none !important;
          }
          .top-nav-wrap + div div[role="radiogroup"] > label:has(input:checked) {
            background: rgba(255,255,255,0.08);
            border-color: rgba(255,255,255,0.10);
            border-bottom-color: transparent;
            font-weight: 600;
          }
        </style>
        <div class="top-nav-wrap"></div>
        """,
        unsafe_allow_html=True,
    )
    if icons:
        labels = [f"{icons.get(s, '')} {s}".strip() for s in sections]
        idx = st.radio(
            "topnav",
            list(range(len(sections))),
            format_func=lambda i: labels[i],
            horizontal=True,
            label_visibility="collapsed",
            key=key,
        )
        return sections[idx]
    return st.radio(
        "topnav",
        sections,
        horizontal=True,
        label_visibility="collapsed",
        key=key,
    )


def active_filters_chips(
    state: FiltersState,
    on_clear: Callable[[str], None] | None = None,
) -> None:
    """Muestra chips con × para cada filtro activo."""
    labels = state.active_labels()
    if not labels:
        return
    cols = st.columns(len(labels) + 1)
    for i, label in enumerate(labels):
        with cols[i]:
            safe = _html.escape(label)
            st.markdown(
                f'<span style="display:inline-block;background:rgba(255,255,255,0.06);'
                f"border:1px solid rgba(255,255,255,0.10);border-radius:999px;"
                f'padding:2px 10px;font-size:0.78rem;color:#E0E0E0;white-space:nowrap">'
                f"{safe}</span>",
                unsafe_allow_html=True,
            )
