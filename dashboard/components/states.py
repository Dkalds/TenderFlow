"""Estados de UI — empty_state, error_state, loading_skeleton, guarded_render.

El shimmer animation usa la clase `.skeleton` definida en `theme/css.py`.
La animación se desactiva automáticamente con `prefers-reduced-motion: reduce`.
"""

from __future__ import annotations

import functools
import html as _html
import traceback
from collections.abc import Callable
from contextlib import contextmanager

import streamlit as st

from dashboard.components.icons import icon


def empty_state(
    icon_name: str | None,
    title: str,
    message: str,
    cta_label: str | None = None,
    cta_cb: Callable[[], None] | None = None,
) -> None:
    """Estado vacío: icono SVG + título + mensaje + CTA opcional.

    Args:
        icon_name: clave de icono Lucide (ej. "inbox", "alert-triangle").
                   Por compatibilidad acepta también un emoji legacy: si
                   `icon_name` no está en el catálogo, se renderiza tal cual.

    Usa `role=status` y `aria-live=polite` para que lectores de pantalla lo
    anuncien cuando aparece dinámicamente.
    """
    safe_title = _html.escape(title)
    safe_msg = _html.escape(message)

    if icon_name and len(icon_name) <= 2:
        # Probable emoji legacy → mapear o renderizar como texto.
        icon_html = (
            f'<div style="font-size:2.4rem;line-height:1" aria-hidden="true">{icon_name}</div>'
        )
    elif icon_name:
        icon_html = icon(icon_name, size=44)
    else:
        icon_html = ""

    st.markdown(
        f'<div role="status" aria-live="polite" class="empty-state">'
        f'<div class="es-icon">{icon_html}</div>'
        f'<div class="es-title">{safe_title}</div>'
        f'<div class="es-msg">{safe_msg}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
    if cta_label and cta_cb:
        _, col, _ = st.columns([1, 2, 1])
        with col:
            if st.button(cta_label, use_container_width=True):
                cta_cb()


def error_state(
    title: str,
    message: str,
    suggestion: str | None = None,
    exception: Exception | None = None,
    debug: bool = False,
) -> None:
    """Estado de error con título, descripción amigable y sugerencia de acción.

    En modo debug (URL `?debug=1`) muestra el traceback completo en un expander.
    """
    st.markdown(
        f'<div role="alert" aria-live="assertive" class="error-banner">'
        f"{icon('alert-triangle', 18)}"
        f"<div><strong>{_html.escape(title)}</strong>"
        f"<span>{_html.escape(message)}</span></div>"
        f"</div>",
        unsafe_allow_html=True,
    )
    if suggestion:
        st.caption(f"💡 {suggestion}")
    if debug and exception:
        with st.expander("Detalles técnicos (modo debug)"):
            st.code(traceback.format_exc(), language="python")


def loading_skeleton(rows: int = 3, height: str = "72px") -> None:
    """Filas de carga con animación shimmer (clase `.skeleton` del CSS global).

    En entornos sin Streamlit runtime renderiza divs simples sin animación.
    """
    for _ in range(rows):
        st.markdown(
            f'<div class="skeleton" style="height:{height}"></div>',
            unsafe_allow_html=True,
        )


def kpi_skeleton(cols: int = 5) -> None:
    """Skeleton placeholder con la forma exacta de una fila de KPI cards.

    Renderiza *cols* columnas, cada una con un div que replica la estructura
    visual de `.kpi-card` (label rect + value rect + sparkline rect) con la
    animación shimmer, eliminando el salto visual al cargar los datos reales.
    """
    columns = st.columns(cols)
    inner = (
        '<div class="skeleton-kpi-label"></div>'
        '<div class="skeleton-kpi-value"></div>'
        '<div class="skeleton-kpi-spark"></div>'
    )
    for col in columns:
        with col:
            st.markdown(
                f'<div class="kpi-card skeleton-card">{inner}</div>',
                unsafe_allow_html=True,
            )


def card_skeleton(rows: int = 3) -> None:
    """Skeleton placeholder con la forma exacta de una top-card.

    Cada fila replica `.top-card` (amount rect + title rect + meta rect).
    """
    inner = (
        '<div class="skeleton-tc-amount"></div>'
        '<div class="skeleton-tc-title"></div>'
        '<div class="skeleton-tc-meta"></div>'
    )
    for _ in range(rows):
        st.markdown(
            f'<div class="top-card skeleton-card">{inner}</div>',
            unsafe_allow_html=True,
        )


@contextmanager
def with_loading(message: str = "Cargando…"):
    """Context manager: muestra `st.spinner` mientras ejecuta el bloque.

    Si ocurre una excepción la captura y la muestra con `error_state`.

    Ejemplo::

        with with_loading("Calculando previsión…"):
            fc = build_forecast_df(df, adj)
    """
    with st.spinner(message):
        try:
            yield
        except Exception as exc:
            error_state(
                "Error al cargar los datos",
                str(exc),
                suggestion="Revisa los filtros activos o recarga la página.",
                exception=exc,
                debug=bool(st.query_params.get("debug")),
            )


def guarded_render(fn: Callable) -> Callable:
    """Decorador para funciones `render(ctx)` de páginas.

    Envuelve la ejecución en try/except y muestra `error_state` en vez de
    dejar que Streamlit propague el error a pantalla completa.

    Activa el traceback completo si `?debug=1` está en la URL.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        debug = bool(st.query_params.get("debug"))
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            # Loggear siempre el traceback completo al stdout para diagnóstico
            # local (Streamlit silencia las excepciones de páginas decoradas).
            traceback.print_exc()
            error_state(
                f"Error al renderizar '{fn.__name__}'",
                "Ha ocurrido un problema inesperado en esta sección.",
                suggestion="Prueba reduciendo el rango de fechas o limpiando los filtros.",
                exception=exc,
                debug=debug,
            )

    return wrapper
