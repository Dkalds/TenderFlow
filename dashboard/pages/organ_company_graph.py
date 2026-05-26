"""Página Competencia — Red Órgano-Empresa.

Grafo bipartito interactivo que visualiza las relaciones contractuales
entre órganos contratantes y empresas adjudicatarias, con métricas
de importe, conteo y frecuencia temporal.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:
    import networkx as nx  # type: ignore[import-untyped]
except ModuleNotFoundError:  # pragma: no cover
    nx = None  # type: ignore[assignment]

from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state, guarded_render
from dashboard.data_loader import load_adjudicaciones
from dashboard.pages._base import PageContext
from dashboard.utils.format import fmt_eur
from services.organ_company_graph import build_bipartite_graph

# ── Colores por tipo de nodo ──────────────────────────────────────────────
_ORGANO_COLOR = "#1f77b4"  # azul
_EMPRESA_COLOR = "#2ca02c"  # verde


# ── Helpers ───────────────────────────────────────────────────────────────


def _build_figure(
    graph: dict,
    ctx: PageContext,
) -> go.Figure:
    """Construye la figura Plotly del grafo bipartito."""
    assert nx is not None  # caller already checked

    G = nx.Graph()
    organos = [n for n in graph["nodes"] if n["type"] == "organo"]
    empresas = [n for n in graph["nodes"] if n["type"] == "empresa"]

    for n in graph["nodes"]:
        G.add_node(n["name"], bipartite=0 if n["type"] == "organo" else 1)
    for e in graph["edges"]:
        G.add_edge(e["organo"], e["empresa"], weight=e["contratos"])

    # Layout: intentar bipartite_layout, fallback a spring
    try:
        top_nodes = {n["name"] for n in organos}
        pos = nx.bipartite_layout(G, top_nodes, align="horizontal", scale=2.0)
    except Exception:  # pragma: no cover
        pos = nx.spring_layout(
            G,
            k=2.5 / max(len(G.nodes) ** 0.5, 1),
            iterations=50,
            seed=42,
        )

    # --- Edge traces -------------------------------------------------------
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    for e in graph["edges"]:
        if e["organo"] not in pos or e["empresa"] not in pos:
            continue
        x0, y0 = pos[e["organo"]]
        x1, y1 = pos[e["empresa"]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    # Edge width proportional to importe (normalize to 0.5-4 range)
    avg_width = 1.2

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=avg_width, color="rgba(150,150,150,0.35)"),
        hoverinfo="none",
    )

    # --- Individual edge hover (midpoints) ---------------------------------
    mid_x, mid_y, mid_text = [], [], []
    for e in graph["edges"]:
        if e["organo"] not in pos or e["empresa"] not in pos:
            continue
        x0, y0 = pos[e["organo"]]
        x1, y1 = pos[e["empresa"]]
        mid_x.append((x0 + x1) / 2)
        mid_y.append((y0 + y1) / 2)
        mid_text.append(
            f"<b>{e['organo'][:40]}</b><br>"
            f"↕ <b>{e['empresa'][:40]}</b><br>"
            f"Contratos: {e['contratos']}<br>"
            f"Importe: {e['importe_total']:,.0f} €<br>"
            f"Frecuencia: {e['frecuencia_anual']:.1f} contratos/año"
        )

    edge_hover_trace = go.Scatter(
        x=mid_x,
        y=mid_y,
        mode="markers",
        marker=dict(size=8, color="rgba(0,0,0,0)", line=dict(width=0)),
        hovertext=mid_text,
        hoverinfo="text",
        showlegend=False,
    )

    # --- Órgano nodes (blue) -----------------------------------------------
    organo_x = [pos[n["name"]][0] for n in organos if n["name"] in pos]
    organo_y = [pos[n["name"]][1] for n in organos if n["name"] in pos]
    organos_in_pos = [n for n in organos if n["name"] in pos]
    organo_size = [max(10, min(50, n["degree"] * 6)) for n in organos_in_pos]
    organo_hover = [
        f"<b>🏛 {n['name'][:50]}</b><br>"
        f"Tipo: Órgano contratante<br>"
        f"Empresas vinculadas: {n['degree']}<br>"
        f"Importe total: {n['importe_total']:,.0f} €"
        for n in organos_in_pos
    ]

    organo_trace = go.Scatter(
        x=organo_x,
        y=organo_y,
        mode="markers+text",
        name="Órganos",
        marker=dict(
            size=organo_size,
            color=_ORGANO_COLOR,
            symbol="square",
            line=dict(width=1.5, color="white"),
            opacity=0.85,
        ),
        text=[n["name"][:18] for n in organos_in_pos],
        textposition="top center",
        textfont=dict(size=7, color=_ORGANO_COLOR),
        hovertext=organo_hover,
        hoverinfo="text",
    )

    # --- Empresa nodes (green) ---------------------------------------------
    empresa_x = [pos[n["name"]][0] for n in empresas if n["name"] in pos]
    empresa_y = [pos[n["name"]][1] for n in empresas if n["name"] in pos]
    empresas_in_pos = [n for n in empresas if n["name"] in pos]
    empresa_size = [max(10, min(50, n["degree"] * 6)) for n in empresas_in_pos]
    empresa_hover = [
        f"<b>🏢 {n['name'][:50]}</b><br>"
        f"Tipo: Empresa adjudicataria<br>"
        f"Órganos vinculados: {n['degree']}<br>"
        f"Importe total: {n['importe_total']:,.0f} €"
        for n in empresas_in_pos
    ]

    empresa_trace = go.Scatter(
        x=empresa_x,
        y=empresa_y,
        mode="markers+text",
        name="Empresas",
        marker=dict(
            size=empresa_size,
            color=_EMPRESA_COLOR,
            symbol="circle",
            line=dict(width=1.5, color="white"),
            opacity=0.85,
        ),
        text=[n["name"][:18] for n in empresas_in_pos],
        textposition="bottom center",
        textfont=dict(size=7, color=_EMPRESA_COLOR),
        hovertext=empresa_hover,
        hoverinfo="text",
    )

    # --- Figure ------------------------------------------------------------
    fig = go.Figure(data=[edge_trace, edge_hover_trace, organo_trace, empresa_trace])
    fig.update_layout(
        template=ctx.plotly_template,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            font=dict(size=11),
        ),
        height=620,
        margin=dict(t=40, b=20, l=20, r=20),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
    )
    return fig


def _render_detail_table(graph: dict) -> None:
    """Tabla de detalle de aristas del grafo."""
    if not graph["edges"]:
        return

    df = pd.DataFrame(graph["edges"])
    df = df.rename(
        columns={
            "organo": "Órgano Contratante",
            "empresa": "Empresa Adjudicataria",
            "contratos": "Contratos",
            "importe_total": "Importe (€)",
            "frecuencia_anual": "Frecuencia (c/año)",
        }
    )
    df = df.sort_values("Importe (€)", ascending=False)

    with st.expander("📋 Tabla detallada de relaciones", expanded=False):
        st.dataframe(
            df.style.format(
                {
                    "Importe (€)": "{:,.0f}",
                    "Frecuencia (c/año)": "{:.1f}",
                }
            ),
            use_container_width=True,
            hide_index=True,
            height=400,
        )


# ── Render principal ──────────────────────────────────────────────────────


@guarded_render
def render(ctx: PageContext) -> None:
    adj = load_adjudicaciones()
    if adj.empty:
        empty_state(
            "🔗",
            "Sin datos de adjudicación",
            "El pipeline aún no ha importado adjudicaciones. "
            "Ejecuta la actualización para visualizar la red órgano-empresa.",
        )
        return

    # Filter to active scope (respects sidebar filters)
    ids_filtradas = set(ctx.df["id_externo"])
    adj_ci = adj[adj["licitacion_id"].isin(ids_filtradas)].copy()

    if adj_ci.empty:
        st.info("No hay adjudicaciones para los filtros actuales.")
        return

    st.title("🔗 Red Órgano-Empresa")
    st.caption(
        "Grafo bipartito de relaciones contractuales entre órganos contratantes "
        "y empresas adjudicatarias. Tamaño de nodo = grado de conexiones."
    )

    # ── KPI row ────────────────────────────────────────────────────────────
    n_organos = adj_ci["organo_contratacion"].nunique()
    n_empresas = adj_ci["empresa_key"].nunique()
    total_contratos = len(adj_ci)
    total_importe = adj_ci["importe_adjudicado"].sum(skipna=True)

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            kpi_card("Órganos", f"{n_organos:,}", icon="🏛"),
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            kpi_card("Empresas", f"{n_empresas:,}", icon="🏢"),
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            kpi_card("Adjudicaciones", f"{total_contratos:,}", icon="📄"),
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            kpi_card("Importe total", fmt_eur(total_importe), icon="💰"),
            unsafe_allow_html=True,
        )

    st.divider()

    # ── Controls ───────────────────────────────────────────────────────────
    if nx is None:  # pragma: no cover
        st.warning(
            "La librería `networkx` no está instalada. El grafo bipartito no está disponible."
        )
        return

    c1, c2, c3 = st.columns(3)
    min_contratos = c1.slider(
        "Mín. contratos por relación",
        min_value=1,
        max_value=10,
        value=2,
        key="bip_min_contratos",
    )
    top_organos = c2.slider(
        "Top órganos (por importe)",
        min_value=5,
        max_value=50,
        value=20,
        key="bip_top_organos",
    )
    top_empresas = c3.slider(
        "Top empresas (por importe)",
        min_value=5,
        max_value=50,
        value=20,
        key="bip_top_empresas",
    )

    # ── Build graph ────────────────────────────────────────────────────────
    graph = build_bipartite_graph(
        adj_ci,
        min_contratos=min_contratos,
        top_organos=top_organos,
        top_empresas=top_empresas,
    )

    if not graph["nodes"]:
        st.info(
            "No hay relaciones órgano-empresa suficientes con los filtros actuales. "
            "Prueba a reducir el mínimo de contratos."
        )
        return

    n_organos_graph = sum(1 for n in graph["nodes"] if n["type"] == "organo")
    n_empresas_graph = sum(1 for n in graph["nodes"] if n["type"] == "empresa")

    # ── Graph visualization ────────────────────────────────────────────────
    fig = _build_figure(graph, ctx)
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"🏛 {n_organos_graph} órganos · 🏢 {n_empresas_graph} empresas · "
        f"🔗 {len(graph['edges'])} relaciones contractuales"
    )

    # ── Detail table ───────────────────────────────────────────────────────
    _render_detail_table(graph)
