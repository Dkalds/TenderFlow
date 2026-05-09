"""Componente KPI card — genera HTML para st.markdown.

Soporta:
- sparkline: lista de valores -> mini-grafico SVG inline (ultimos N periodos).
- tooltip: explicacion de la formula (atributo title del aria-label).
- anomaly: badge cuando el valor actual se desvia >N sigmas del historico.
- delta / delta_up: texto comparativo con flecha y color.
"""

from __future__ import annotations

import html as _html
from collections.abc import Sequence


def _catmull_rom_to_bezier(pts: list[tuple[float, float]]) -> str:
    """Convert a sequence of (x, y) points to a smooth SVG cubic-bezier path.

    Uses Catmull-Rom spline conversion with tension=0 (uniform parameterisation).
    Returns the ``d`` attribute string for an SVG ``<path>`` element.
    """
    if len(pts) < 2:
        return ""
    if len(pts) == 2:
        return f"M{pts[0][0]:.1f},{pts[0][1]:.1f}L{pts[1][0]:.1f},{pts[1][1]:.1f}"

    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(len(pts) - 1):
        p0 = pts[max(i - 1, 0)]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[min(i + 2, len(pts) - 1)]

        # Control points (Catmull-Rom → cubic Bezier, alpha=1/6)
        cp1x = p1[0] + (p2[0] - p0[0]) / 6
        cp1y = p1[1] + (p2[1] - p0[1]) / 6
        cp2x = p2[0] - (p3[0] - p1[0]) / 6
        cp2y = p2[1] - (p3[1] - p1[1]) / 6

        d += f"C{cp1x:.1f},{cp1y:.1f} {cp2x:.1f},{cp2y:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def _sparkline_svg(
    values: Sequence[float],
    width: int = 80,
    height: int = 24,
    up: bool = True,
) -> str:
    """Genera un SVG inline de sparkline a partir de una lista de valores.

    - Normaliza al rango [0, height-2] para dejar margen visual.
    - Dibuja smooth bezier curve con gradient fill de area.
    - Marca min/max con puntos pequeños y último punto con efecto glow.
    - Devuelve cadena vacía si hay menos de 2 puntos válidos.
    """
    vals = [float(v) for v in values if v is not None and v == v]  # descarta NaN
    if len(vals) < 2:
        return ""

    lo = min(vals)
    hi = max(vals)
    rng = hi - lo if hi > lo else 1.0
    n = len(vals)
    step = width / (n - 1) if n > 1 else width

    pts: list[tuple[float, float]] = []
    min_idx = 0
    max_idx = 0
    for i, v in enumerate(vals):
        x = i * step
        # Y invertido (SVG origen arriba-izquierda)
        y = (height - 2) - ((v - lo) / rng) * (height - 4) - 1
        pts.append((x, y))
        if v <= vals[min_idx]:
            min_idx = i
        if v >= vals[max_idx]:
            max_idx = i

    curve_d = _catmull_rom_to_bezier(pts)
    # Area fill path: curve + vertical line down + horizontal back + close
    area_d = f"{curve_d}L{pts[-1][0]:.1f},{height - 1:.1f}L0,{height - 1:.1f}Z"

    last_x, last_y = pts[-1]
    color = "#86BC25" if up else "#E21836"
    grad_id = "spkg" if up else "spkr"

    # Build SVG
    svg_parts: list[str] = [
        f'<svg class="sparkline" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" aria-hidden="true">',
        # Gradient definition
        f"<defs>"
        f'<linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.25"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/>'
        f"</linearGradient>"
        f"</defs>",
        # Area fill with gradient
        f'<path d="{area_d}" fill="url(#{grad_id})" stroke="none"/>',
        # Smooth curve
        f'<path d="{curve_d}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
    ]

    # Min/max markers (skip if they coincide with last point)
    for idx, opacity in ((min_idx, 0.5), (max_idx, 0.5)):
        if idx != n - 1:
            svg_parts.append(
                f'<circle cx="{pts[idx][0]:.1f}" cy="{pts[idx][1]:.1f}" '
                f'r="1.5" fill="{color}" opacity="{opacity}"/>'
            )

    # Last-point glow: outer ring + solid dot
    svg_parts.append(
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="4" fill="{color}" opacity="0.18"/>'
    )
    svg_parts.append(f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2" fill="{color}"/>')

    svg_parts.append("</svg>")
    return "".join(svg_parts)


def kpi_card(
    label: str,
    value: str,
    delta: str | None = None,
    delta_up: bool = True,
    icon: str = "",
    sparkline: Sequence[float] | None = None,
    tooltip: str | None = None,
    anomaly: bool = False,
) -> str:
    """Devuelve un string HTML con la tarjeta KPI.

    Args:
        label: título corto del KPI.
        value: valor principal (ya formateado).
        delta: texto comparativo opcional.
        delta_up: si True pinta ▲ verde, si False ▼ rojo.
        icon: emoji decorativo.
        sparkline: serie histórica opcional para mini-gráfico inline.
        tooltip: explicación de la fórmula (atributo title).
        anomaly: si True, añade badge ⚠ indicando desviación anómala.
    """
    safe_label = _html.escape(str(label))
    safe_value = _html.escape(str(value))
    aria = f"{safe_label}: {safe_value}"

    delta_html = ""
    if delta:
        cls = "up" if delta_up else "down"
        arrow = "▲" if delta_up else "▼"
        safe_delta = _html.escape(str(delta))
        delta_html = f'<div class="delta {cls}">{arrow} {safe_delta}</div>'

    icon_html = f'<span class="icon" aria-hidden="true">{icon}</span>' if icon else ""

    # Tooltip: se renderiza como atributo title en el contenedor (hover nativo).
    title_attr = f' title="{_html.escape(tooltip)}"' if tooltip else ""

    # Anomaly badge (no bloquea lectura — flotante arriba-derecha junto al icono).
    from dashboard.components.icons import icon as _icon  # local import para evitar circular

    anomaly_html = (
        '<span class="anomaly-badge" aria-label="Valor anómalo" '
        f'title="Desvío significativo vs histórico">{_icon("alert-triangle", 14)}</span>'
        if anomaly
        else ""
    )

    sparkline_html = ""
    if sparkline:
        sparkline_html = (
            f'<div class="sparkline-wrap">{_sparkline_svg(list(sparkline), up=delta_up)}</div>'
        )

    return (
        f'<div class="kpi-card" role="group" aria-label="{aria}"{title_attr}>'
        f"{icon_html}{anomaly_html}"
        f'<div class="label">{safe_label}</div>'
        f'<div class="value">{safe_value}</div>'
        f"{sparkline_html}"
        f"{delta_html}"
        f"</div>"
    )
