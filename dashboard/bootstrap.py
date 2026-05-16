"""Bootstrap del dashboard — configuración única por proceso.

Centraliza todo lo que debe ejecutarse UNA sola vez al arrancar:
  - logging estructurado y tracing
  - st.set_page_config (debe ser la primera llamada Streamlit)
  - CSS anti-flash + tema premium
  - autenticación
  - registro de plantillas Plotly

Importado al inicio de app.py; no contiene lógica de renderizado.
"""

from __future__ import annotations

import streamlit as st

from dashboard.auth import check_password
from dashboard.theme import (
    TOKENS,
    build_css,
    get_color_sequence,
    register_plotly_template,
)
from observability import configure_logging, configure_tracing
from observability.logging import bind_session_context


def bootstrap() -> tuple[str, list[str]]:
    """Inicializa el proceso del dashboard.

    Debe llamarse al inicio de app.py, antes de cualquier otra llamada
    a Streamlit.

    Returns:
        (plotly_template_name, color_sequence)
    """
    # ── Observabilidad ──────────────────────────────────────────────────
    configure_logging()
    configure_tracing(service_name="licitaciones-dashboard")

    # ── Page config (debe ser la primera llamada st.*) ──────────────────
    st.set_page_config(
        page_title="Licitaciones · Sector Público",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Anti-flash: ocultar chrome nativo inmediatamente ─────────────────
    st.markdown(
        "<style>"
        '#MainMenu,footer,[data-testid="stSidebarNav"],[data-testid="stSidebarNavSeparator"],'
        '[data-testid="stAppDeployButton"],[data-testid="stMainMenu"],'
        '[data-testid="stDecoration"],[data-testid="stStatusWidget"]'
        "{display:none!important;visibility:hidden!important}"
        '[data-testid="stToolbar"]{visibility:hidden!important}'
        '[data-testid="stExpandSidebarButton"]{visibility:visible!important;display:block!important}'
        "</style>",
        unsafe_allow_html=True,
    )

    # ── Tema premium ────────────────────────────────────────────────────
    st.markdown(build_css(TOKENS), unsafe_allow_html=True)

    # ── Autenticación ───────────────────────────────────────────────────
    check_password()

    # ── Correlation ID de sesión ────────────────────────────────────────
    bind_session_context()

    # ── Plantillas Plotly ───────────────────────────────────────────────
    plotly_template = register_plotly_template(TOKENS)
    color_sequence = get_color_sequence(TOKENS)

    return plotly_template, color_sequence
