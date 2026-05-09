"""Lazy-loading wrapper for heavy chart sections."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

import streamlit as st


@contextmanager
def lazy_section(key: str, label: str = "Cargar sección") -> Generator[bool, None, None]:
    """Context manager that defers rendering until the user expands or clicks.

    Usage:
        with lazy_section("heavy_chart", "Ver mapa geográfico") as should_render:
            if should_render:
                # expensive chart code here
                st.plotly_chart(fig, ...)
    """
    if f"_lazy_{key}" not in st.session_state:
        st.session_state[f"_lazy_{key}"] = False

    expanded = st.session_state[f"_lazy_{key}"]

    if not expanded:
        if st.button(f"📊 {label}", key=f"_lazy_btn_{key}", use_container_width=True):
            st.session_state[f"_lazy_{key}"] = True
            st.rerun()
        yield False
    else:
        yield True
