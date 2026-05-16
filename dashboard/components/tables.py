"""Wrapper de tabla — abstrae st.dataframe / AgGrid para uso uniforme."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd
import streamlit as st

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    _AGGRID = True
except ImportError:
    _AGGRID = False

_AUTO_THRESHOLD = 100  # filas por encima de las cuales se activa AgGrid en modo 'auto'


def paginate_df(
    df: pd.DataFrame,
    *,
    page_size: int = 50,
    key: str = "table_page",
) -> pd.DataFrame:
    """Muestra controles prev/next y devuelve sólo las filas de la página actual.

    Args:
        df:         DataFrame completo ya filtrado.
        page_size:  Número de filas por página.
        key:        Clave de sesión para guardar el número de página actual.

    Returns:
        Slice del DataFrame correspondiente a la página actual.
    """
    total = len(df)
    if total <= page_size:
        return df

    n_pages = max(1, (total + page_size - 1) // page_size)
    if key not in st.session_state:
        st.session_state[key] = 0

    page: int = int(st.session_state[key])
    page = max(0, min(page, n_pages - 1))
    st.session_state[key] = page

    col_prev, col_info, col_next = st.columns([1, 4, 1])
    with col_prev:
        if st.button("← Anterior", key=f"{key}_prev", disabled=page == 0):
            st.session_state[key] = page - 1
            st.rerun()
    with col_info:
        first_row = page * page_size + 1
        last_row = min((page + 1) * page_size, total)
        st.caption(f"Filas {first_row}–{last_row} de {total:,}  (página {page + 1}/{n_pages})")
    with col_next:
        if st.button("Siguiente →", key=f"{key}_next", disabled=page >= n_pages - 1):
            st.session_state[key] = page + 1
            st.rerun()

    start = page * page_size
    return df.iloc[start : start + page_size]


def data_table(
    df: pd.DataFrame,
    *,
    column_config: dict[str, Any] | None = None,
    height: int | None = None,
    key: str | None = None,
    mode: str = "auto",
    page_size: int = 50,
    enable_filter: bool = True,
    enable_export: bool = True,
    selection_mode: str | None = None,
) -> dict[str, Any] | None:
    """Renderiza un DataFrame con configuración estándar.

    mode='auto'   → AgGrid cuando len(df) > 100 (si está instalado).
    mode='aggrid' → fuerza AgGrid (fallback a native si no está instalado).
    mode='native' → fuerza st.dataframe.

    Returns selection event dict when selection_mode is set, else None.
    """
    use_aggrid = _AGGRID and mode != "native" and (mode == "aggrid" or len(df) > _AUTO_THRESHOLD)

    if use_aggrid:
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_default_column(
            filter=enable_filter,
            resizable=True,
            sortable=True,
            wrapText=False,
            autoHeight=False,
        )
        gb.configure_pagination(
            enabled=True,
            paginationAutoPageSize=False,
            paginationPageSize=page_size,
        )
        if enable_export:
            gb.configure_grid_options(
                suppressExcelExport=False,
                suppressCsvExport=False,
            )
        AgGrid(
            df,
            gridOptions=gb.build(),
            update_mode=GridUpdateMode.NO_UPDATE,
            allow_unsafe_jscode=False,
            theme="streamlit",
            height=height or 400,
            use_container_width=True,
            key=key,
        )
        return None
    else:
        extra_kw: dict[str, Any] = {}
        if height is not None:
            extra_kw["height"] = height
        if selection_mode:
            extra_kw["selection_mode"] = selection_mode
            extra_kw["on_select"] = "rerun"
        event = st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config=column_config or {},
            key=key,
            **extra_kw,
        )
        if selection_mode and event is not None:
            return cast(dict[str, Any], event)
        return None
