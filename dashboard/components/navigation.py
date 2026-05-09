"""Componentes de navegación — breadcrumb, sub-nav y filtros activos."""

from __future__ import annotations

import html as _html
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import streamlit as st

if TYPE_CHECKING:
    from dashboard.filters.state import FiltersState

_MAX_CHIPS_PER_ROW = 4


def _remove_filter(key: str, value: str | None) -> None:
    """Elimina un filtro individual de session_state.

    - Si ``value`` es None el filtro es escalar: se borra o resetea la clave.
    - Si ``value`` es str se elimina sólo ese valor de la lista almacenada.
    """
    if value is None:
        current = st.session_state.get(key)
        if isinstance(current, str):
            st.session_state[key] = ""
        elif isinstance(current, int | float):
            st.session_state[key] = 0
        elif key in st.session_state:
            del st.session_state[key]
    else:
        current: list[Any] = st.session_state.get(key, [])
        st.session_state[key] = [v for v in current if v != value]


def breadcrumb(section: str, page: str, description: str | None = None) -> None:
    """Renderiza `Sección › Página` y, opcionalmente, una línea de descripción."""
    safe_section = _html.escape(section)
    safe_page = _html.escape(page)
    desc_html = f'<p class="bc-desc">{_html.escape(description)}</p>' if description else ""
    st.markdown(
        f'<nav aria-label="breadcrumb">'
        f'<div class="bc">'
        f'<span class="bc-section">{safe_section}</span>'
        f'<span class="bc-sep" aria-hidden="true">›</span>'
        f'<span class="bc-page" aria-current="page">{safe_page}</span>'
        f"</div>{desc_html}</nav>",
        unsafe_allow_html=True,
    )


def sub_nav(pages: list[str], *, key: str, icons: dict[str, str] | None = None) -> str:
    """Radio horizontal para navegar entre sub-páginas de una sección."""
    if icons:
        labels = [f"{icons.get(p, '')} {p}".strip() for p in pages]
        idx = st.radio(
            "p",
            list(range(len(pages))),
            format_func=lambda i: labels[i],
            horizontal=True,
            label_visibility="collapsed",
            key=key,
        )
        return pages[idx]
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
    """Muestra chips interactivos (con ×) para cada filtro activo.

    Clicar el × de un chip elimina ese filtro individual de session_state
    sin necesidad de abrir el sidebar.
    """
    items = state.active_items()
    if not items:
        return

    rows = [items[i : i + _MAX_CHIPS_PER_ROW] for i in range(0, len(items), _MAX_CHIPS_PER_ROW)]
    for row in rows:
        # Alternar columnas: [chip_wide, x_narrow, chip_wide, x_narrow, ...]
        weights: list[int] = []
        for _ in row:
            weights.extend([9, 1])
        cols = st.columns(weights, gap="small")

        for j, (label, key, value) in enumerate(row):
            chip_col = cols[j * 2]
            btn_col = cols[j * 2 + 1]
            safe = _html.escape(label)
            chip_col.markdown(
                f'<span class="filter-chip">{safe}</span>',
                unsafe_allow_html=True,
            )
            if btn_col.button(
                "×",
                key=f"chip_rm_{key}_{value or ''}",
                help=f"Quitar filtro: {label}",
            ):
                _remove_filter(key, value)
