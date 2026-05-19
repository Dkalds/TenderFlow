"""Componentes de tarjeta — top_card para licitaciones y adjudicaciones."""

from __future__ import annotations

import html as _html
from collections.abc import Generator
from contextlib import contextmanager

import streamlit as st

from dashboard.utils.security import safe_url


@contextmanager
def chart_card(
    title: str,
    subtitle: str | None = None,
    *,
    exportable: bool = False,
) -> Generator[None]:
    """Context manager — envuelve contenido en una chart-card glass-morphism.

    Renderiza una tarjeta con borde, fondo desenfocado y cabecera de título.
    El efecto visual se aplica via CSS sobre el ``stVerticalBlockBorderWrapper``
    cuando éste contiene un hijo ``.chart-card-header``.

    Args:
        title: Título de la tarjeta.
        subtitle: Subtítulo opcional.
        exportable: Si True, añade un botón de descarga PNG usando la API
            de Plotly ``toImage`` en el cliente (solo funciona con gráficas Plotly).

    Usage::

        with chart_card("Distribución por estado", subtitle="Últimos 90 días",
                        exportable=True):
            st.plotly_chart(fig, use_container_width=True)
    """
    safe_title = _html.escape(title)
    # Identificador único para anclar el botón de exportación al gráfico correcto
    _card_id = f"cc_{abs(hash(title)) % 100000}"

    header_html = (
        f'<div class="chart-card-header" id="{_card_id}-hdr">'
        f'<div class="chart-card-title">{safe_title}</div>'
    )
    if subtitle:
        header_html += f'<div class="chart-card-sub">{_html.escape(subtitle)}</div>'
    header_html += "</div>"

    container = st.container(border=True)
    with container:
        st.markdown(header_html, unsafe_allow_html=True)
        yield
        if exportable:
            _safe_fname = safe_title.replace(" ", "_").lower()[:30]
            _export_js = f"""
            <script>
            (function() {{
              var cardId = '{_card_id}';
              var fname  = '{_safe_fname}';
              var btn = document.getElementById(cardId + '-exp-btn');
              if (!btn) return;
              btn.addEventListener('click', function() {{
                // Buscar el SVG de Plotly más cercano al encabezado
                var hdr = document.getElementById(cardId + '-hdr');
                if (!hdr) return;
                var card = hdr.closest('[data-testid="stVerticalBlockBorderWrapper"]')
                          || hdr.parentElement;
                var svg = card ? card.querySelector('.main-svg') : null;
                if (!svg) {{ alert('No se encontró el gráfico SVG.'); return; }}
                var serializer = new XMLSerializer();
                var svgStr = serializer.serializeToString(svg);
                var blob = new Blob([svgStr], {{type: 'image/svg+xml'}});
                var url = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = url; a.download = fname + '.svg';
                document.body.appendChild(a); a.click();
                document.body.removeChild(a);
                setTimeout(function() {{ URL.revokeObjectURL(url); }}, 1000);
              }});
            }})();
            </script>
            """
            st.markdown(
                f'<button id="{_card_id}-exp-btn" '
                f'style="background:transparent;border:1px solid rgba(255,255,255,0.15);'
                f"color:rgba(255,255,255,0.5);border-radius:5px;padding:3px 10px;"
                f'font-size:0.75rem;cursor:pointer;margin-top:4px">'
                f"⬇ SVG</button>"
                f"{_export_js}",
                unsafe_allow_html=True,
            )


def top_card(
    amount: str,
    title: str,
    meta: str,
    *,
    url: str | None = None,
    highlight: str | None = None,
) -> None:
    """Renderiza una top-card con importe, título enlazado y metadatos.

    Args:
        amount: Texto del importe (ya formateado, e.g. "1.23 M€").
        title: Título de la licitación (se escapa y trunca a 120 chars).
        meta: Línea de metadatos. Siempre se escapa automáticamente.
        url: URL de la licitación. Se valida con safe_url.
        highlight: Si se proporciona, se añade en negrita al final del meta
                   (también escapado automáticamente).
    """
    href = safe_url(url)
    safe_title = _html.escape(str(title)[:120])
    meta_escaped = _html.escape(str(meta))
    if highlight is not None:
        meta_html = f"{meta_escaped} · <b>{_html.escape(str(highlight))}</b>"
    else:
        meta_html = meta_escaped

    # Si la URL es inválida (None) → renderizar título como texto plano sin enlace.
    if href is None:
        title_html = f'<div class="title">{safe_title}</div>'
    else:
        safe_href = _html.escape(href, quote=True)
        title_html = (
            f'<div class="title">'
            f'<a href="{safe_href}" target="_blank" rel="noopener noreferrer">'
            f"{safe_title}</a></div>"
        )

    st.markdown(
        f'<div class="top-card">'
        f'<div class="amount">{_html.escape(amount)}</div>'
        f"{title_html}"
        f'<div class="meta">{meta_html}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


# ── Nivel → (color token CSS var, icon name) ───────────────────────────────
_BADGE_CONFIG: dict[str, tuple[str, str]] = {
    "success": ("var(--color-success)", "check-circle"),
    "warning": ("var(--color-warning)", "alert-triangle"),
    "danger": ("var(--color-danger)", "x-circle"),
    "info": ("var(--color-accent-primary)", "info"),
    "neutral": ("var(--color-text-muted)", "circle-dot"),
}


def status_badge(level: str, label: str) -> str:
    """Devuelve HTML de un badge pill con color semántico e icono.

    Args:
        level: ``"success"``, ``"warning"``, ``"danger"``, ``"info"`` o
               ``"neutral"``.
        label: Texto del badge (se escapa automáticamente).

    Returns:
        String HTML listo para ``st.markdown(..., unsafe_allow_html=True)``.
    """
    from dashboard.components.icons import icon as _icon  # evitar circular

    color, icon_name = _BADGE_CONFIG.get(level, _BADGE_CONFIG["neutral"])
    safe_label = _html.escape(str(label))
    icon_html = _icon(icon_name, size=12)
    return (
        f'<span class="status-badge status-badge--{level}" '
        f'style="--badge-color:{color}">'
        f"{icon_html} {safe_label}"
        f"</span>"
    )


def with_tooltip(content_html: str, tooltip_text: str) -> str:
    """Envuelve *content_html* en un contenedor con tooltip CSS-only.

    El tooltip aparece encima del elemento al hacer hover.  No requiere JS.

    Args:
        content_html: HTML del elemento a envolver (no se escapa).
        tooltip_text: Texto plano del tooltip (se escapa automáticamente).

    Returns:
        String HTML listo para ``st.markdown(..., unsafe_allow_html=True)``.
    """
    safe_tip = _html.escape(str(tooltip_text))
    return f'<span class="has-tooltip" data-tip="{safe_tip}">{content_html}</span>'
