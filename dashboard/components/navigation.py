"""Componentes de navegación — breadcrumb, sub-nav y filtros activos."""

from __future__ import annotations

import html as _html
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import streamlit as st

from dashboard.session_keys import NAV_CUR_PAGE, NAV_PREV_PAGE, NAV_PREV_SECTION

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
        current_list: list[Any] = st.session_state.get(key, [])
        st.session_state[key] = [v for v in current_list if v != value]


def _navigate_to_section(section: str) -> None:
    """Navega a la primera página de una sección actualizando session_state."""
    st.session_state["nav_section"] = section


def breadcrumb(section: str, page: str, description: str | None = None) -> None:
    """Renderiza `Sección › Página` con la sección como enlace clicable."""
    safe_section = _html.escape(section)
    safe_page = _html.escape(page)
    desc_html = f'<p class="bc-desc">{_html.escape(description)}</p>' if description else ""

    # El span de sección se envuelve con styling de link para indicar que es clicable
    st.markdown(
        f'<nav aria-label="breadcrumb">'
        f'<div class="bc">'
        f'<span class="bc-section bc-section-link" style="cursor:pointer;text-decoration:underline dotted;opacity:0.8">{safe_section}</span>'
        f'<span class="bc-sep" aria-hidden="true">›</span>'
        f'<span class="bc-page" aria-current="page">{safe_page}</span>'
        f"</div>{desc_html}</nav>",
        unsafe_allow_html=True,
    )
    # Botón invisible que activa la navegación a la sección al ser clicado
    # Usamos CSS para superponer el botón sobre el texto del breadcrumb
    st.markdown(
        """
        <style>
        div[data-testid="stButton"]:has(button[title="Volver a la sección"]) {
            position: relative; margin-top: -2.4em; opacity: 0;
            width: fit-content; pointer-events: auto;
        }
        div[data-testid="stButton"]:has(button[title="Volver a la sección"]) button {
            padding: 0 !important; min-height: 0 !important;
            height: 1.6em; font-size: 0.85rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if st.button(section, key=f"bc_nav_{section}", help="Volver a la sección"):
        _navigate_to_section(section)
        st.rerun()


def back_button() -> None:
    """Renderiza un botón '← Volver' si hay una página anterior en el historial.

    Sólo visible cuando ``session_state[NAV_PREV_PAGE]`` está definido,
    es decir, cuando el usuario llegó a la página actual desde otra sub-página
    distinta (ej. desde Resumen → Detalle).
    """
    prev_page: str | None = st.session_state.get(NAV_PREV_PAGE)
    prev_section: str | None = st.session_state.get(NAV_PREV_SECTION)
    if not prev_page or not prev_section:
        return

    safe_prev = _html.escape(prev_page)
    # Botón compacto con ← y el nombre de la página anterior
    st.markdown(
        """
        <style>
        div[data-testid="stButton"]:has(button[title="Volver a página anterior"]) button {
            background: transparent !important;
            border: 1px solid var(--color-border-card) !important;
            color: var(--color-text-muted) !important;
            font-size: 0.82rem !important;
            padding: 2px 10px !important;
            min-height: 0 !important;
            height: 1.7em !important;
            border-radius: 6px !important;
            margin-bottom: 4px !important;
        }
        div[data-testid="stButton"]:has(button[title="Volver a página anterior"]) button:hover {
            color: var(--color-text-primary) !important;
            border-color: var(--color-border-hover) !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if st.button(
        f"← {safe_prev}",
        key="btn_back",
        help="Volver a página anterior",
    ):
        # Cannot set nav_section directly after widget is instantiated.
        # Store a pending nav request that app.py consumes before the widget renders.
        st.session_state["_pending_nav_section"] = prev_section
        # Determinar la clave del sub-nav de esa sección para restaurar la página
        nav_key = f"nav_page_{prev_section}"
        from dashboard.router import SECTIONS  # local import to avoid circular

        pages = SECTIONS.get(prev_section, [])
        if prev_page in pages:
            st.session_state[nav_key] = pages.index(prev_page)
        # Limpiar historial para que el botón desaparezca en la página de destino
        st.session_state.pop(NAV_PREV_PAGE, None)
        st.session_state.pop(NAV_PREV_SECTION, None)
        st.rerun()


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
          .top-nav-wrap { margin: -4px 0 14px 0; }
          .top-nav-wrap + div div[role="radiogroup"] {
            gap: 2px !important;
            flex-wrap: wrap;
            background: var(--color-bg-elev-1);
            border: 1px solid var(--color-border-card);
            border-radius: 10px;
            padding: 4px !important;
            display: inline-flex !important;
            box-shadow: var(--shadow-sm);
          }
          .top-nav-wrap + div div[role="radiogroup"] > label {
            background: transparent;
            border: 1px solid transparent;
            border-radius: 7px;
            padding: 7px 14px !important;
            margin: 0 !important;
            transition: background .18s ease, color .18s ease, transform .1s ease;
            cursor: pointer;
            font-weight: 500;
            font-size: 0.86rem;
            color: var(--color-text-muted);
          }
          .top-nav-wrap + div div[role="radiogroup"] > label:hover {
            background: rgba(255,255,255,0.04);
            color: var(--color-text-primary);
          }
          .top-nav-wrap + div div[role="radiogroup"] > label > div:first-child {
            display: none !important;
          }
          .top-nav-wrap + div div[role="radiogroup"] > label:has(input:checked) {
            background: var(--color-bg-elev-2);
            border-color: var(--color-border-hover);
            color: var(--color-text-primary);
            font-weight: 600;
            box-shadow: 0 1px 0 rgba(255,255,255,0.04) inset, 0 1px 2px rgba(0,0,0,0.2);
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
