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


def _sparkline_svg(
    values: Sequence[float],
    width: int = 80,
    height: int = 24,
    up: bool = True,
) -> str:
    """Genera un SVG inline de sparkline a partir de una lista de valores.

    - Normaliza al rango [0, height-2] para dejar margen visual.
    - Dibuja polyline + último punto como círculo destacado.
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

    points = []
    for i, v in enumerate(vals):
        x = i * step
        # Y invertido (SVG origen arriba-izquierda)
        y = (height - 2) - ((v - lo) / rng) * (height - 4) - 1
        points.append(f"{x:.1f},{y:.1f}")

    path = " ".join(points)
    last_x, last_y = points[-1].split(",")
    color = "#86BC25" if up else "#E21836"
    fill_color = "rgba(134,188,37,0.12)" if up else "rgba(226,24,54,0.10)"

    # Area fill: polygon closes back along the bottom edge of the SVG
    polygon_pts = f"{path} {width:.1f},{height - 1:.1f} 0,{height - 1:.1f}"

    return (
        f'<svg class="sparkline" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" aria-hidden="true">'
        f'<polygon points="{polygon_pts}" fill="{fill_color}" stroke="none"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round" points="{path}"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2" fill="{color}"/>'
        f"</svg>"
    )


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
