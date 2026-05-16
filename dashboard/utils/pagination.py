"""Paginación server-side para DataFrames grandes en Streamlit.

Slice el DataFrame *antes* de enviarlo al navegador, evitando que 10k+ filas
lleguen al DOM del cliente.  Renderiza controles de navegación (prev / next /
selector de página) usando ``st.session_state`` para mantener la página activa
entre reruns.

Uso típico::

    from dashboard.utils.pagination import paginated_df

    page_df, controls_rendered = paginated_df(
        df,
        page_size=100,
        key="detalle_table",
    )
    data_table(page_df, key="detalle_table_grid")
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st


def paginated_df(
    df: pd.DataFrame,
    *,
    page_size: int = 100,
    key: str = "pagination",
) -> tuple[pd.DataFrame, int]:
    """Devuelve el slice de ``df`` correspondiente a la página activa.

    Renderiza automáticamente los controles de paginación (prev / number select
    / next) y un contador ``Mostrando X-Y de N filas``.

    Args:
        df: DataFrame completo ya filtrado.
        page_size: Número de filas por página (default 100).
        key: Prefijo de clave de ``session_state`` — usa uno distinto por tabla.

    Returns:
        Tuple (slice_df, current_page_1indexed).
    """
    total = len(df)
    if total == 0:
        return df, 1

    n_pages = max(1, math.ceil(total / page_size))
    page_key = f"_pg_{key}"

    # Inicializar o validar que la página almacenada sigue siendo válida
    current = int(st.session_state.get(page_key, 1))
    current = max(1, min(current, n_pages))
    st.session_state[page_key] = current

    start = (current - 1) * page_size
    end = min(start + page_size, total)

    # ── Controles ────────────────────────────────────────────────────────
    col_info, col_prev, col_page, col_next = st.columns([4, 1, 2, 1])

    with col_info:
        st.caption(f"Mostrando {start + 1:,}–{end:,} de {total:,} filas")

    with col_prev:
        if st.button("◀", key=f"_{key}_prev", disabled=current <= 1, use_container_width=True):
            st.session_state[page_key] = current - 1
            st.rerun()

    with col_page:
        # Selectbox para saltar a una página concreta
        page_labels = [str(p) for p in range(1, n_pages + 1)]
        chosen = st.selectbox(
            "Página",
            options=page_labels,
            index=current - 1,
            key=f"_{key}_sel",
            label_visibility="collapsed",
        )
        chosen_int = int(chosen)
        if chosen_int != current:
            st.session_state[page_key] = chosen_int
            st.rerun()

    with col_next:
        if st.button(
            "▶", key=f"_{key}_next", disabled=current >= n_pages, use_container_width=True
        ):
            st.session_state[page_key] = current + 1
            st.rerun()

    return df.iloc[start:end].copy(), current


def reset_pagination(key: str) -> None:
    """Resetea la página a 1 para ``key`` (útil al cambiar filtros)."""
    st.session_state[f"_pg_{key}"] = 1
