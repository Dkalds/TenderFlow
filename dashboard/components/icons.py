"""Sistema de iconos SVG inline — basado en Lucide (MIT, https://lucide.dev).

Reemplaza los emojis dispersos por la app por SVGs uniformes que escalan,
heredan `currentColor` y se ven idénticos en todos los sistemas operativos.

Uso típico::

    from dashboard.components.icons import icon
    st.markdown(f"{icon('refresh-cw', 16)} Refrescar", unsafe_allow_html=True)

Los paths SVG son fragmentos de Lucide (sin el wrapper `<svg>`); `icon()`
añade el wrapper con `width`, `height` y `stroke="currentColor"`.
"""

from __future__ import annotations

# Atributos del wrapper <svg> compartidos por todos los iconos.
_SVG_ATTRS = (
    'xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"'
)

# Solo el contenido interno del SVG (paths, circles, lines, etc.).
# Ampliar este dict cuando se añadan nuevos call sites.
_ICON_PATHS: dict[str, str] = {
    "layout-dashboard": (
        '<rect width="7" height="9" x="3" y="3" rx="1"/>'
        '<rect width="7" height="5" x="14" y="3" rx="1"/>'
        '<rect width="7" height="9" x="14" y="12" rx="1"/>'
        '<rect width="7" height="5" x="3" y="16" rx="1"/>'
    ),
    "trending-up": (
        '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>'
    ),
    "table": (
        '<path d="M12 3v18"/><rect width="18" height="18" x="3" y="3" rx="2"/>'
        '<path d="M3 9h18"/><path d="M3 15h18"/>'
    ),
    "building-2": (
        '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/>'
        '<path d="M6 12H4a2 2 0 0 0-2 2v8h4"/>'
        '<path d="M18 9h2a2 2 0 0 1 2 2v11h-4"/>'
        '<path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>'
    ),
    "map": (
        '<polygon points="3 6 9 3 15 6 21 3 21 18 15 21 9 18 3 21"/>'
        '<line x1="9" x2="9" y1="3" y2="18"/><line x1="15" x2="15" y1="6" y2="21"/>'
    ),
    "boxes": (
        '<path d="M2.97 12.92A2 2 0 0 0 2 14.63v3.24a2 2 0 0 0 .97 1.71l3 1.8a2 2 0 0 0 2.06 0L12 19v-5.5l-5-3-4.03 2.42Z"/>'
        '<path d="m7 16.5-4.74-2.85"/><path d="m7 16.5 5-3"/><path d="M7 16.5v5.17"/>'
        '<path d="M12 13.5V19l3.97 2.38a2 2 0 0 0 2.06 0l3-1.8a2 2 0 0 0 .97-1.71v-3.24a2 2 0 0 0-.97-1.71L17 10.5l-5 3Z"/>'
        '<path d="m17 16.5-5-3"/><path d="m17 16.5 4.74-2.85"/><path d="M17 16.5v5.17"/>'
        '<path d="M7.97 4.42A2 2 0 0 0 7 6.13v4.37l5 3 5-3V6.13a2 2 0 0 0-.97-1.71l-3-1.8a2 2 0 0 0-2.06 0l-3 1.8Z"/>'
        '<path d="M12 8 7.26 5.15"/><path d="m12 8 4.74-2.85"/><path d="M12 13.5V8"/>'
    ),
    "users": (
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>'
    ),
    "bell": (
        '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>'
        '<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>'
    ),
    "bookmark": ('<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>'),
    "activity": ('<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>'),
    "refresh-cw": (
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
        '<path d="M21 3v5h-5"/>'
        '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
        '<path d="M3 21v-5h5"/>'
    ),
    "search": ('<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>'),
    "calendar": (
        '<rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>'
        '<line x1="16" x2="16" y1="2" y2="6"/>'
        '<line x1="8" x2="8" y1="2" y2="6"/>'
        '<line x1="3" x2="21" y1="10" y2="10"/>'
    ),
    "filter": ('<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>'),
    "x": ('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
    "chevron-right": ('<path d="m9 18 6-6-6-6"/>'),
    "alert-triangle": (
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>'
        '<path d="M12 9v4"/><path d="M12 17h.01"/>'
    ),
    "info": ('<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>'),
    "inbox": (
        '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>'
        '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>'
    ),
    "database": (
        '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
        '<path d="M3 5V19A9 3 0 0 0 21 19V5"/>'
        '<path d="M3 12A9 3 0 0 0 21 12"/>'
    ),
    "clock": ('<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>'),
    "git-compare": (
        '<circle cx="5" cy="6" r="3"/><circle cx="19" cy="18" r="3"/>'
        '<path d="M12 6h5a2 2 0 0 1 2 2v7"/><path d="M12 18H7a2 2 0 0 1-2-2V9"/>'
    ),
    "trash-2": (
        '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/>'
        '<path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
    ),
    "pie-chart": (
        '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>'
    ),
    "bar-chart-3": (
        '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>'
    ),
    "euro": (
        '<path d="M4 10h12"/><path d="M4 14h9"/>'
        '<path d="M19 6a7.7 7.7 0 0 0-5.2-2A7.9 7.9 0 0 0 6 12c0 4.4 3.5 8 7.8 8 2 0 3.8-.8 5.2-2"/>'
    ),
    # ── Iconos adicionales (Fase mejoras-visuales) ───────────────────────
    "download": (
        '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>'
        '<polyline points="7 10 12 15 17 10"/>'
        '<line x1="12" x2="12" y1="15" y2="3"/>'
    ),
    "flame": (
        '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 '
        '.5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 3z"/>'
    ),
    "check-circle": (
        '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'
    ),
    "x-circle": ('<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>'),
    "lightbulb": (
        '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/>'
        '<path d="M9 18h6"/><path d="M10 22h4"/>'
    ),
    "circle-dot": ('<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="1"/>'),
}


# ─────────────────────────────────────────────────────────────────────────
# Logo (monograma azul SAP) — usado en sidebar brand y header
# ─────────────────────────────────────────────────────────────────────────
LOGO_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" '
    'viewBox="0 0 32 32" fill="none" aria-label="Licitaciones SAP">'
    '<rect x="1.5" y="1.5" width="29" height="29" rx="7" '
    'fill="rgba(134,188,36,0.12)" stroke="#86BC24" stroke-width="1.5"/>'
    '<path d="M9 22 L9 10 L13 10 L13 17 L17 10 L21 10 L17 16 L23 22 L18 22 L13 17 L13 22 Z" '
    'fill="#86BC24"/>'
    "</svg>"
)


def icon(name: str, size: int = 16, color: str | None = None) -> str:
    """Devuelve el markup `<svg>` para el icono solicitado.

    Args:
        name: clave en `_ICON_PATHS`. Si no existe, devuelve un cuadrado vacío
              (fallback silencioso para no romper la UI en producción).
        size: ancho y alto en píxeles.
        color: color CSS opcional. Si es None hereda `currentColor` del padre,
               lo que permite estilar desde CSS (`.kpi-card .icon { color: ...}`).
    """
    inner = _ICON_PATHS.get(name)
    if inner is None:
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}"'
            ' viewBox="0 0 24 24"><rect width="24" height="24" fill="none"/></svg>'
        )
    style = f' style="color:{color}"' if color else ""
    return (
        f'<svg {_SVG_ATTRS} width="{size}" height="{size}" aria-hidden="true"{style}>{inner}</svg>'
    )


def icon_inline(name: str, size: int = 14, color: str | None = None) -> str:
    """Variante de `icon()` con `display:inline-flex` y baseline alineada al texto.

    Útil para iconos que van pegados a una palabra (chips, breadcrumbs).
    """
    svg = icon(name, size=size, color=color)
    # Reemplazo del primer `<svg ` para inyectar style inline.
    return svg.replace(
        "<svg ",
        '<svg style="display:inline-block;vertical-align:-2px;margin-right:4px" ',
        1,
    )
