"""Sincronización bidireccional entre URL query-params y filtros de sesión."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.filters import FiltersState
from dashboard.session_keys import (
    FS_CCAAS,
    FS_ESTADOS,
    FS_IMP_MIN,
    FS_ORGANOS,
    FS_Q,
    FS_RANGO,
    FS_TIPOS,
    LIC_FOCUS,
    NAV_SECTION,
    QP_LOADED,
)


def init_from_query_params(df_full: pd.DataFrame) -> None:
    """Carga los filtros iniciales desde los query-params de la URL.

    Solo se ejecuta en la primera carga (cuando ``QP_LOADED`` no está en
    ``st.session_state``).  Valida los valores contra los datos disponibles
    para no inyectar opciones inválidas.
    """
    if QP_LOADED in st.session_state:
        return

    init_filters = FiltersState.from_query_params(dict(st.query_params))

    if init_filters.q:
        st.session_state[FS_Q] = init_filters.q

    if init_filters.estados:
        valid_estados = set(df_full["estado_desc"].dropna().unique())
        st.session_state[FS_ESTADOS] = [
            e for e in init_filters.estados if e in valid_estados
        ]

    if init_filters.ccaas:
        valid_ccaas = set(df_full["ccaa"].dropna().unique())
        st.session_state[FS_CCAAS] = [
            c for c in init_filters.ccaas if c in valid_ccaas
        ]

    if init_filters.organos:
        valid_organos = set(df_full["organo_contratacion"].dropna().unique())
        st.session_state[FS_ORGANOS] = [
            o for o in init_filters.organos if o in valid_organos
        ]

    if init_filters.tipos_proy:
        valid_tipos = set(df_full["tipo_proyecto"].dropna().unique())
        st.session_state[FS_TIPOS] = [
            t for t in init_filters.tipos_proy if t in valid_tipos
        ]

    if init_filters.importe_min > 0:
        st.session_state[FS_IMP_MIN] = init_filters.importe_min

    if init_filters.rango:
        st.session_state[FS_RANGO] = init_filters.rango

    # Deep-link a licitación individual: ?lic=ID_EXTERNO
    if init_filters.lic_id:
        st.session_state[LIC_FOCUS] = init_filters.lic_id
        st.session_state[NAV_SECTION] = "Vista General"
        st.session_state["nav_page_Vista General"] = 2  # index de "Detalle" en SECTIONS

    st.session_state[QP_LOADED] = True


def sync_to_query_params(filters: FiltersState) -> None:
    """Actualiza los query-params de la URL para que reflejen los filtros activos.

    Elimina los parámetros que ya no están presentes en los filtros para
    mantener la URL limpia y compartible.
    """
    new_qp = filters.to_query_params()
    cur_qp = dict(st.query_params)
    if cur_qp != new_qp:
        for key in list(cur_qp):
            if key not in new_qp:
                del st.query_params[key]
        st.query_params.update(new_qp)
