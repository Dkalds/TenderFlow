"""Renderiza los filtros del sidebar y devuelve un FiltersState."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.icons import icon
from dashboard.filters.state import FiltersState
from dashboard.session_keys import FILTER_KEYS, QP_LOADED

# Claves de session_state que el botón "Limpiar filtros" debe resetear.
_FILTER_STATE_KEYS = FILTER_KEYS


def _group_header(label: str, icon_name: str) -> None:
    """Cabecera estilizada para agrupar bloques de filtros en el sidebar."""
    st.markdown(
        f'<div class="filter-group-header">{icon(icon_name, 12)} {label}</div>',
        unsafe_allow_html=True,
    )


def _clear_filters() -> None:
    """Resetea las claves de filtros del session_state."""
    for key in _FILTER_STATE_KEYS:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state[QP_LOADED] = False  # forzar relectura desde URL vacía


def render_sidebar_filters(df_full: pd.DataFrame) -> FiltersState:
    """Dibuja los controles de filtro en el sidebar activo y devuelve el estado."""
    _group_header("Buscar", "search")
    q = st.text_input(
        "Buscar",
        "",
        key="fs_q",
        placeholder="Título, descripción, CPV…",
        label_visibility="collapsed",
    )

    fmin = df_full["fecha_publicacion"].min()
    fmax = df_full["fecha_publicacion"].max()
    if pd.notna(fmin) and pd.notna(fmax):
        _group_header("Periodo", "calendar")
        rango = st.date_input(
            "Rango fechas",
            (fmin.date(), fmax.date()),
            min_value=fmin.date(),
            max_value=fmax.date(),
            key="fs_rango",
            label_visibility="collapsed",
        )
    else:
        rango = None

    _group_header("Segmentación", "filter")
    estados = st.multiselect(
        "Estado",
        sorted(df_full["estado_desc"].dropna().unique()),
        key="fs_estados",
    )
    ccaas = st.multiselect(
        "Comunidad Autónoma",
        sorted(df_full["ccaa"].dropna().unique()),
        key="fs_ccaas",
    )
    organos = st.multiselect(
        "Órgano contratante",
        sorted(df_full["organo_contratacion"].dropna().unique()),
        key="fs_organos",
    )
    tipos_proy = st.multiselect(
        "Tipo de proyecto",
        sorted(df_full["tipo_proyecto"].dropna().unique()),
        key="fs_tipos",
    )

    _group_header("Importe", "euro")
    importe_min = st.number_input(
        "Importe mínimo (€)",
        min_value=0,
        value=0,
        step=10000,
        key="fs_imp_min",
        label_visibility="collapsed",
    )

    # ── Filtros avanzados (comparativa) ────────────────────────────
    rango_b = None
    with st.expander("Filtros avanzados"):
        comparar = st.toggle("Modo comparativa", key="fs_comparar")
        if comparar and pd.notna(fmin) and pd.notna(fmax):
            st.caption("Rango B (comparar con)")
            rango_b_raw = st.date_input(
                "Rango B",
                (fmin.date(), fmax.date()),
                min_value=fmin.date(),
                max_value=fmax.date(),
                key="fs_rango_b",
                label_visibility="collapsed",
            )
            if isinstance(rango_b_raw, tuple) and len(rango_b_raw) == 2:
                rango_b = rango_b_raw

    # ── Acciones ──────────────────────────────────────────────────
    st.button(
        "Limpiar filtros",
        on_click=_clear_filters,
        use_container_width=True,
        key="fs_clear",
        help="Resetea todos los filtros a sus valores por defecto.",
    )

    return FiltersState(
        q=q,
        rango=rango if isinstance(rango, tuple) and len(rango) == 2 else None,
        estados=list(estados),
        ccaas=list(ccaas),
        organos=list(organos),
        tipos_proy=list(tipos_proy),
        importe_min=int(importe_min),
        comparar=st.session_state.get("fs_comparar", False),
        rango_b=rango_b,
    )
