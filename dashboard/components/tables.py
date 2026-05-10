"""Wrapper de tabla — abstrae st.dataframe / AgGrid para uso uniforme."""

from __future__ import annotations

import pandas as pd
import streamlit as st

try:
    from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

    _AGGRID = True
except ImportError:
    _AGGRID = False

_AUTO_THRESHOLD = 100  # filas por encima de las cuales se activa AgGrid en modo 'auto'


def data_table(
    df: pd.DataFrame,
    *,
    column_config: dict | None = None,
    height: int | None = None,
    key: str | None = None,
    mode: str = "auto",
    page_size: int = 50,
    enable_filter: bool = True,
    enable_export: bool = True,
) -> None:
    """Renderiza un DataFrame con configuración estándar.

    mode='auto'   → AgGrid cuando len(df) > 100 (si está instalado).
    mode='aggrid' → fuerza AgGrid (fallback a native si no está instalado).
    mode='native' → fuerza st.dataframe.
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
    else:
        extra_kw: dict = {}
        if height is not None:
            extra_kw["height"] = height
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config=column_config or {},
            key=key,
            **extra_kw,
        )
