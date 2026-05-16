"""Estados de UI — empty_state, error_state, loading_skeleton, guarded_render.

El shimmer animation usa la clase `.skeleton` definida en `theme/css.py`.
La animación se desactiva automáticamente con `prefers-reduced-motion: reduce`.
"""

from __future__ import annotations

import functools
import html as _html
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import streamlit as st

from dashboard.components.icons import icon


def empty_state(
    icon_name: str | None,
    title: str,
    message: str,
    cta_label: str | None = None,
    cta_cb: Callable[[], None] | None = None,
    illustration: str | None = None,
) -> None:
    """Estado vacío: icono SVG + título + mensaje + CTA opcional.

    Args:
        icon_name: clave de icono Lucide (ej. "inbox", "alert-triangle").
                   Por compatibilidad acepta también un emoji legacy: si
                   `icon_name` no está en el catálogo, se renderiza tal cual.
        illustration: HTML/SVG inline opcional que reemplaza al icono cuando
                      se quiere mostrar una ilustración más elaborada.

    Usa `role=status` y `aria-live=polite` para que lectores de pantalla lo
    anuncien cuando aparece dinámicamente.
    """
    safe_title = _html.escape(title)
    safe_msg = _html.escape(message)

    if illustration:
        icon_html = illustration
    elif icon_name and len(icon_name) <= 2:
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
def with_loading(message: str = "Cargando…") -> Iterator[None]:
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


def guarded_render(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorador para funciones `render(ctx)` de páginas.

    Envuelve la ejecución en try/except y muestra `error_state` en vez de
    dejar que Streamlit propague el error a pantalla completa.

    Activa el traceback completo si `?debug=1` está en la URL.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
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


# ── Ilustraciones SVG inline para empty states ───────────────────────────
# Geometría abstracta ligera — evita dependencias externas y carga instantánea.

_ILLUSTRATION_EMPTY_SEARCH = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96" fill="none" aria-hidden="true">'
    '<circle cx="42" cy="42" r="26" stroke="rgba(134,188,36,0.25)" stroke-width="2.5"/>'
    '<circle cx="42" cy="42" r="14" fill="rgba(134,188,36,0.07)"/>'
    '<path d="M62 62 L78 78" stroke="rgba(134,188,36,0.35)" stroke-width="3" stroke-linecap="round"/>'
    '<circle cx="42" cy="36" r="3" fill="rgba(134,188,36,0.30)"/>'
    '<path d="M35 48 Q42 54 49 48" stroke="rgba(134,188,36,0.25)" stroke-width="1.5" fill="none" stroke-linecap="round"/>'
    "</svg>"
)

_ILLUSTRATION_EMPTY_DATA = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96" fill="none" aria-hidden="true">'
    '<rect x="16" y="56" width="12" height="24" rx="3" fill="rgba(134,188,36,0.15)" stroke="rgba(134,188,36,0.30)" stroke-width="1.5"/>'
    '<rect x="34" y="40" width="12" height="40" rx="3" fill="rgba(134,188,36,0.20)" stroke="rgba(134,188,36,0.35)" stroke-width="1.5"/>'
    '<rect x="52" y="28" width="12" height="52" rx="3" fill="rgba(134,188,36,0.28)" stroke="rgba(134,188,36,0.45)" stroke-width="1.5"/>'
    '<rect x="70" y="48" width="12" height="32" rx="3" fill="rgba(134,188,36,0.15)" stroke="rgba(134,188,36,0.30)" stroke-width="1.5"/>'
    '<path d="M22 55 L40 39 L58 27 L76 47" stroke="rgba(134,188,36,0.50)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="4 3"/>'
    "</svg>"
)

_ILLUSTRATION_ERROR = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96" viewBox="0 0 96 96" fill="none" aria-hidden="true">'
    '<circle cx="48" cy="48" r="32" stroke="rgba(226,24,54,0.20)" stroke-width="2"/>'
    '<circle cx="48" cy="48" r="22" fill="rgba(226,24,54,0.06)"/>'
    '<path d="M40 40 L56 56 M56 40 L40 56" stroke="rgba(226,24,54,0.55)" stroke-width="3" stroke-linecap="round"/>'
    "</svg>"
)

ILLUSTRATIONS: dict[str, str] = {
    "empty-search": _ILLUSTRATION_EMPTY_SEARCH,
    "empty-data": _ILLUSTRATION_EMPTY_DATA,
    "error": _ILLUSTRATION_ERROR,
}


def render_splash() -> None:
    """Pantalla de carga mientras Streamlit inicializa datos.

    Inyecta un overlay CSS que desaparece cuando la página termina de renderizar.
    Llamar al principio de ``app.py`` o de cada página, antes de cargar datos.
    """
    st.markdown(
        """
<style>
#splash-overlay {
  position: fixed; inset: 0; z-index: 9998;
  background: #0B0B0D;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  gap: 20px;
  animation: splashFadeOut 0.4s ease-out 0.8s both;
}
@keyframes splashFadeOut {
  from { opacity: 1; pointer-events: auto; }
  to   { opacity: 0; pointer-events: none; visibility: hidden; }
}
.splash-logo { animation: splashBounce 0.6s cubic-bezier(0.22,1,0.36,1) both; }
@keyframes splashBounce {
  from { opacity: 0; transform: scale(0.85) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}
.splash-bar {
  width: 160px; height: 2px;
  background: rgba(134,188,36,0.18);
  border-radius: 2px;
  overflow: hidden;
}
.splash-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, transparent, #86BC24, transparent);
  background-size: 200% 100%;
  animation: splashShimmer 0.9s ease-in-out 0.1s infinite;
}
@keyframes splashShimmer {
  0%   { background-position: -100% 0; }
  100% { background-position:  200% 0; }
}
</style>
<div id="splash-overlay" role="status" aria-live="polite" aria-label="Cargando…">
  <div class="splash-logo">
    <svg xmlns="http://www.w3.org/2000/svg" width="52" height="52" viewBox="0 0 32 32" fill="none">
      <rect x="1.5" y="1.5" width="29" height="29" rx="7"
            fill="rgba(134,188,36,0.12)" stroke="#86BC24" stroke-width="1.5"/>
      <path d="M9 22 L9 10 L13 10 L13 17 L17 10 L21 10 L17 16 L23 22 L18 22 L13 17 L13 22 Z"
            fill="#86BC24"/>
    </svg>
  </div>
  <div class="splash-bar"><div class="splash-bar-fill"></div></div>
</div>
""",
        unsafe_allow_html=True,
    )


def inject_favicon() -> None:
    """Inyecta el favicon SVG corporativo en la pestaña del navegador.

    Streamlit permite sobreescribir el favicon con ``st.set_page_config`` pero
    sólo acepta emojis o URLs. Este helper inyecta un data-URI SVG vía JS para
    un icono vectorial perfecto en cualquier resolución.
    """
    favicon_svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
        "<rect width='32' height='32' rx='7' fill='%230B0B0D'/>"
        "<rect x='1' y='1' width='30' height='30' rx='6.5' fill='none' stroke='%2386BC24' stroke-width='1.5'/>"
        "<path d='M8 22 L8 10 L12 10 L12 17 L16 10 L20 10 L16 16 L22 22 L17 22 L12 17 L12 22 Z' fill='%2386BC24'/>"
        "</svg>"
    )
    data_uri = f"data:image/svg+xml,{favicon_svg}"
    st.markdown(
        f"<script>var l=document.querySelector(\"link[rel*='icon']\");"
        f'if(!l){{l=document.createElement("link");l.rel="icon";document.head.appendChild(l);}}'
        f'l.type="image/svg+xml";l.href="{data_uri}";</script>',
        unsafe_allow_html=True,
    )
