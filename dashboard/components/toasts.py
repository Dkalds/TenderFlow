"""Wrappers de notificaciones — st.toast con iconos semánticos."""

from __future__ import annotations

import streamlit as st


def notify_success(message: str) -> None:
    st.toast(message, icon=":material/check_circle:")


def notify_error(message: str) -> None:
    st.toast(message, icon=":material/error:")
