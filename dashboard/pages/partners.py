"""Página Competencia — Ecosistema de Partners.

Grafo de co-adjudicaciones, rankings de ganadores por segmento
y buscador de partners potenciales para subcontratación SAP.
"""

from __future__ import annotations

from typing import Any

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
from services.partners import (
    build_partnership_graph,
    company_profile,
    segment_winners,
    suggest_partners,
)

_SAP_KEYWORDS = ["SAP", "ERP", "S/4HANA", "HANA", "BASIS", "ABAP", "Fiori", "BW", "BTP"]


# ── Tab 1: Grafo de relaciones ────────────────────────────────────────────


def _render_graph_tab(ctx: PageContext, adj: pd.DataFrame) -> None:
    """Network graph interactivo de co-adjudicaciones en UTEs."""
    if nx is None:  # pragma: no cover
        st.warning(
            "La librería `networkx` no está instalada. El grafo de partners no está disponible."
        )
        return

    c1, c2 = st.columns(2)
    min_contratos = c1.slider("Mín. contratos juntos", 1, 10, 2, key="graph_min")
    top_nodes = c2.slider("Máx. empresas en grafo", 10, 150, 50, key="graph_top")

    graph = build_partnership_graph(adj, min_contratos=min_contratos, top_nodes=top_nodes)
    if not graph["nodes"]:
        st.info("No hay co-adjudicaciones UTE suficientes con los filtros actuales.")
        return

    # Build networkx graph for layout
    G = nx.Graph()
    for node in graph["nodes"]:
        G.add_node(node["name"], importe=node["importe"], contratos=node["contratos"])
    for edge in graph["edges"]:
        G.add_edge(edge["source"], edge["target"], weight=edge["contratos"])

    pos = nx.spring_layout(G, k=2.5 / max(len(G.nodes) ** 0.5, 1), iterations=50, seed=42)

    # Edge traces
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []
    edge_hover: list[str] = []
    for edge in graph["edges"]:
        x0, y0 = pos[edge["source"]]
        x1, y1 = pos[edge["target"]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])
        edge_hover.append(
            f"{edge['source'][:30]} ↔ {edge['target'][:30]}<br>"
            f"Contratos: {edge['contratos']}<br>"
            f"Importe: {edge['importe']:,.0f} €"
        )

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=0.8, color="rgba(150,150,150,0.4)"),
        hoverinfo="none",
    )

    # Node traces
    node_x = [pos[n["name"]][0] for n in graph["nodes"]]
    node_y = [pos[n["name"]][1] for n in graph["nodes"]]
    node_size = [max(8, min(50, n["contratos"] * 4)) for n in graph["nodes"]]
    node_color = [n["importe"] for n in graph["nodes"]]
    node_text = [
        f"<b>{n['name'][:35]}</b><br>"
        f"Contratos UTE: {n['contratos']}<br>"
        f"Importe: {n['importe']:,.0f} €"
        for n in graph["nodes"]
    ]

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        marker=dict(
            size=node_size,
            color=node_color,
            colorscale="Greens",
            showscale=True,
            colorbar=dict(title="Importe €", thickness=15),
            line=dict(width=1, color="white"),
        ),
        text=[n["name"][:15] for n in graph["nodes"]],
        textposition="top center",
        textfont=dict(size=8),
        hovertext=node_text,
        hoverinfo="text",
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        template=ctx.plotly_template,
        showlegend=False,
        height=550,
        margin=dict(t=20, b=20, l=20, r=20),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        f"{len(graph['nodes'])} empresas · {len(graph['edges'])} relaciones de co-adjudicación"
    )


# ── Tab 2: Ganadores por segmento ─────────────────────────────────────────


def _render_segment_tab(ctx: PageContext, adj: pd.DataFrame) -> None:
    """Ranking de ganadores con filtro por keyword/CPV."""
    import plotly.express as px

    c1, c2 = st.columns([3, 1])
    keyword = c1.text_input(
        "Filtrar por keyword en título/CPV",
        placeholder="Ej: SAP, consultoría, infraestructura…",
        key="seg_keyword",
    )
    top_n = c2.number_input("Top N", min_value=5, max_value=100, value=20, key="seg_topn")

    if keyword.strip():
        kws = [k.strip() for k in keyword.split(",") if k.strip()]
        ranking = suggest_partners(adj, keywords=kws)
        ranking = ranking.head(int(top_n))
    else:
        ranking = segment_winners(adj, top_n=int(top_n))

    if ranking.empty:
        st.info("Sin resultados para los filtros seleccionados.")
        return

    # KPIs
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            kpi_card("Empresas", f"{len(ranking):,}", icon="🏢"),
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            kpi_card(
                "Importe total",
                fmt_eur(ranking["importe_total"].sum()),
                icon="💰",
            ),
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            kpi_card(
                "Ticket medio",
                fmt_eur(ranking["ticket_medio"].mean()),
                icon="🎫",
            ),
            unsafe_allow_html=True,
        )
    with k4:
        n_organos = ranking["n_organos"].sum()
        st.markdown(
            kpi_card("Órganos distintos", f"{n_organos:,}", icon="🏛"),
            unsafe_allow_html=True,
        )

    # Bar chart
    display = ranking.head(int(top_n)).copy()
    display["empresa_short"] = display["empresa"].str[:40]
    fig = px.bar(
        display.sort_values("importe_total"),
        x="importe_total",
        y="empresa_short",
        orientation="h",
        color="cuota_pct",
        color_continuous_scale="Greens",
        template=ctx.plotly_template,
        labels={
            "importe_total": "Importe adjudicado (€)",
            "empresa_short": "Empresa",
            "cuota_pct": "Cuota %",
        },
        hover_data={"n_contratos": True, "n_organos": True, "cuota_pct": ":.1f"},
    )
    fig.update_layout(height=80 + 28 * len(display), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

    # Tabla detallada
    with st.expander("📋 Tabla detallada", expanded=False):
        show_cols: dict[str, str] = {
            "empresa": "Empresa",
            "n_contratos": "Contratos",
            "importe_total": "Importe (€)",
            "cuota_pct": "Cuota %",
            "ticket_medio": "Ticket medio (€)",
            "n_organos": "Órganos",
        }
        available = {k: v for k, v in show_cols.items() if k in display.columns}
        st.dataframe(
            display[list(available.keys())]
            .rename(columns=available)
            .style.format(
                {"Importe (€)": "{:,.0f}", "Cuota %": "{:.1f}", "Ticket medio (€)": "{:,.0f}"}
            ),
            use_container_width=True,
            hide_index=True,
        )


# ── Tab 3: Buscar partners ───────────────────────────────────────────────


def _render_company_card(profile: dict[str, Any], ctx: PageContext) -> None:
    """Renderiza un card de perfil de empresa."""
    nombre = profile.get("nombre", "—")
    with st.container(border=True):
        top = st.columns([4, 1, 1])
        top[0].markdown(f"**{nombre}**")
        top[1].markdown(f"`{profile.get('n_contratos', 0)} contratos`")
        top[2].markdown(f"`{fmt_eur(profile.get('importe_total', 0))}`")

        meta = st.columns(4)
        meta[0].caption(f"🎫 Ticket medio: {fmt_eur(profile.get('ticket_medio', 0))}")
        meta[1].caption(f"🤝 % UTE: {profile.get('pct_ute', 0):.0f}%")
        pyme_label = "Sí" if profile.get("es_pyme") else "No"
        meta[2].caption(f"📏 PYME: {pyme_label}")
        meta[3].caption(f"🗺 CCAA: {', '.join(profile.get('ccaas', [])[:3])}")

        with st.expander("Ver perfil completo", expanded=False):
            # Top órganos
            organos = profile.get("top_organos", {})
            if organos:
                st.markdown("**Top órganos contratantes:**")
                for org, n in list(organos.items())[:5]:
                    st.caption(f"• {org[:50]} ({n} contratos)")

            # UTE partners
            ute_partners = profile.get("ute_partners", {})
            if ute_partners:
                st.markdown("**Partners frecuentes en UTEs:**")
                for partner, n in list(ute_partners.items())[:5]:
                    st.caption(f"• {partner[:40]} ({n} veces)")

            # CPVs
            cpvs = profile.get("top_cpvs", {})
            if cpvs:
                st.markdown("**Códigos CPV frecuentes:**")
                for cpv, n in list(cpvs.items())[:5]:
                    st.caption(f"• {cpv} ({n})")


def _render_partners_tab(ctx: PageContext, adj: pd.DataFrame) -> None:
    """Buscador de partners potenciales para subcontratación."""
    st.markdown(
        "Introduce keywords de tu especialización para encontrar empresas ganadoras "
        "a las que podrías ofrecer subcontratación."
    )

    c1, c2, c3 = st.columns(3)
    keywords_input = c1.text_input(
        "Keywords (separados por coma)",
        value=", ".join(_SAP_KEYWORDS[:4]),
        key="partner_kw",
    )
    ccaas = ["Todas", *sorted(adj["ccaa"].dropna().unique().tolist())]
    sel_ccaa = c2.selectbox("CCAA", ccaas, key="partner_ccaa")
    min_imp = c3.number_input(
        "Importe mín. (€)",
        min_value=0,
        max_value=50_000_000,
        value=100_000,
        step=50_000,
        key="partner_min_imp",
    )

    keywords = [k.strip() for k in keywords_input.split(",") if k.strip()] if keywords_input else []
    if not keywords:
        st.info("Introduce al menos un keyword para buscar partners.")
        return

    ranking = suggest_partners(
        adj,
        keywords=keywords,
        ccaa=sel_ccaa if sel_ccaa != "Todas" else None,
        min_importe=float(min_imp),
    )

    if ranking.empty:
        st.info("No se encontraron empresas ganadoras para estos criterios.")
        return

    st.success(f"**{len(ranking)}** empresas encontradas para keywords: {', '.join(keywords)}")

    # Show top 20 as cards with profile
    for _, row in ranking.head(20).iterrows():
        profile = company_profile(adj, row["empresa_key"])
        if profile:
            _render_company_card(profile, ctx)


# ── Render principal ──────────────────────────────────────────────────────


@guarded_render
def render(ctx: PageContext) -> None:
    adj = load_adjudicaciones()
    if adj.empty:
        empty_state(
            "🤝",
            "Sin datos de adjudicación",
            "El pipeline aún no ha importado adjudicaciones. "
            "Ejecuta la actualización para obtener el ecosistema de partners.",
        )
        return

    # Filter to active scope (respects sidebar filters)
    ids_filtradas = set(ctx.df["id_externo"])
    adj_ci = adj[adj["licitacion_id"].isin(ids_filtradas)].copy()

    if adj_ci.empty:
        st.info("No hay adjudicaciones para los filtros actuales.")
        return

    st.title("🤝 Ecosistema de Partners")
    st.caption(
        "Analiza quién gana qué, descubre alianzas frecuentes y encuentra "
        "partners potenciales para ofrecer subcontratación especializada."
    )

    # KPI row
    total_empresas = adj_ci["empresa_key"].nunique()
    total_importe = adj_ci["importe_adjudicado"].sum(skipna=True)
    total_utes = adj_ci["es_ute"].sum()
    pyme_pct = adj_ci["es_pyme"].eq(1).sum() / max(1, adj_ci["es_pyme"].notna().sum()) * 100

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            kpi_card("Empresas únicas", f"{total_empresas:,}", icon="🏢"),
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            kpi_card("Importe adjudicado", fmt_eur(total_importe), icon="💰"),
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            kpi_card("Adjudicaciones UTE", f"{int(total_utes):,}", icon="🤝"),
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            kpi_card("% PYME", f"{pyme_pct:.1f}%", icon="📏"),
            unsafe_allow_html=True,
        )

    st.divider()

    tab1, tab2, tab3 = st.tabs(
        [
            "🕸 Grafo de Relaciones",
            "🏆 Ganadores por Segmento",
            "🔍 Buscar Partners",
        ]
    )

    with tab1:
        _render_graph_tab(ctx, adj_ci)
    with tab2:
        _render_segment_tab(ctx, adj_ci)
    with tab3:
        _render_partners_tab(ctx, adj_ci)
