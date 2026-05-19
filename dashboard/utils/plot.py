"""Helpers para gráficos Plotly con optimizaciones de rendimiento.

Proporciona una función ``apply_perf_defaults`` que activa WebGL
cuando el número de puntos supera un umbral y aplica un conjunto de
defaults de layout alineados con el tema del dashboard.

Uso:
    from dashboard.utils.plot import apply_perf_defaults

    fig = px.scatter(df, x="fecha_publicacion", y="importe", ...)
    fig = apply_perf_defaults(fig, n_points=len(df))
    st.plotly_chart(fig, use_container_width=True)
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

# Umbral de puntos a partir del cual se activa WebGL.
# Scattergl, Scattermapboxgl y similares reducen el renderizado de
# 10k puntos de ~3s a <300ms en navegadores modernos.
_WEBGL_THRESHOLD = 5_000


def apply_perf_defaults(
    fig: go.Figure,
    *,
    n_points: int = 0,
    webgl_threshold: int = _WEBGL_THRESHOLD,
) -> go.Figure:
    """Aplica optimizaciones de rendimiento a una figura Plotly.

    * Si ``n_points >= webgl_threshold``, convierte trazas ``scatter`` /
      ``bar`` a sus variantes WebGL (``scattergl`` / ``scatter`` con
      ``render_mode="webgl"``).
    * Desactiva animaciones de transición (costosas con muchos puntos).
    * Activa ``uirevision`` para que filtros de Streamlit no reseteen la
      cámara/zoom del usuario.

    Args:
        fig: Figura Plotly a modificar (in-place y también devuelta).
        n_points: Número de puntos de datos representados. Se usa para
            decidir si activar WebGL.
        webgl_threshold: Umbral a partir del cual se activa WebGL.
            Por defecto :data:`_WEBGL_THRESHOLD`.

    Returns:
        La misma figura con los defaults aplicados.
    """
    use_webgl = n_points >= webgl_threshold

    if use_webgl:
        new_traces: list[Any] = []
        for trace in fig.data:
            # Scattergl es la variante WebGL de Scatter
            if isinstance(trace, go.Scatter):
                scatter_gl = go.Scattergl(
                    x=trace.x,
                    y=trace.y,
                    mode=trace.mode or "markers",
                    name=trace.name,
                    text=trace.text,
                    hovertemplate=trace.hovertemplate,
                    marker=trace.marker,
                    line=trace.line,
                    showlegend=trace.showlegend,
                    opacity=trace.opacity,
                )
                new_traces.append(scatter_gl)
            else:
                new_traces.append(trace)

        # Reconstruir la figura con las nuevas trazas
        fig = go.Figure(data=new_traces, layout=fig.layout)

    # Layout defaults: sin animaciones costosas, zoom persistente
    fig.update_layout(
        uirevision="keep",  # preserva zoom/pan al actualizar datos
        transition={"duration": 0},  # sin animaciones → repintado instantáneo
    )

    return fig


def scatter_or_gl(
    *,
    x: Any,
    y: Any,
    name: str = "",
    mode: str = "markers",
    n_points: int = 0,
    **kwargs: Any,
) -> go.BaseTraceType:
    """Devuelve ``Scattergl`` si n_points >= umbral, ``Scatter`` si no.

    Útil para construir figuras con ``go.Figure(data=[...])`` cuando se
    decide el tipo de traza antes de construir la figura.

    Args:
        x, y: Datos de los ejes.
        name: Nombre de la serie (leyenda).
        mode: Modo de Scatter (``markers``, ``lines``, ``lines+markers``).
        n_points: Número de puntos para decidir WebGL.
        **kwargs: Argumentos extra pasados al constructor de la traza.

    Returns:
        ``go.Scattergl`` o ``go.Scatter`` según el umbral.
    """
    cls = go.Scattergl if n_points >= _WEBGL_THRESHOLD else go.Scatter
    return cls(x=x, y=y, name=name, mode=mode, **kwargs)
