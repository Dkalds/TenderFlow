"""Lectura/escritura de filtros activos en la URL (para compartir enlaces)."""

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
    QP_LOADED,
)


def load_initial(df_full: pd.DataFrame) -> None:
    """Hidrata session_state desde query params (solo primera carga)."""
    if QP_LOADED in st.session_state:
        return
    init = FiltersState.from_query_params(dict(st.query_params))
    if init.q:
        st.session_state[FS_Q] = init.q
    if init.estados:
        valid = set(df_full["estado_desc"].dropna().unique())
        st.session_state[FS_ESTADOS] = [e for e in init.estados if e in valid]
    if init.ccaas:
        valid = set(df_full["ccaa"].dropna().unique())
        st.session_state[FS_CCAAS] = [c for c in init.ccaas if c in valid]
    if init.organos:
        valid = set(df_full["organo_contratacion"].dropna().unique())
        st.session_state[FS_ORGANOS] = [o for o in init.organos if o in valid]
    if init.tipos_proy:
        valid = set(df_full["tipo_proyecto"].dropna().unique())
        st.session_state[FS_TIPOS] = [t for t in init.tipos_proy if t in valid]
    if init.importe_min > 0:
        st.session_state[FS_IMP_MIN] = init.importe_min
    if init.rango:
        st.session_state[FS_RANGO] = init.rango
    st.session_state[QP_LOADED] = True


def sync_to_url(filters: FiltersState) -> None:
    new_qp = filters.to_query_params()
    cur_qp = dict(st.query_params)
    if cur_qp != new_qp:
        for k in list(cur_qp):
            if k not in new_qp:
                del st.query_params[k]
        st.query_params.update(new_qp)
