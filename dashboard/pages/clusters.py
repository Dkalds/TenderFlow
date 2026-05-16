"""Página de Clustering semántico de licitaciones."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from dashboard.clustering import cluster_licitaciones, cluster_summary
from dashboard.components.states import empty_state, guarded_render
from dashboard.components.tables import data_table
from dashboard.pages._base import PageContext


@guarded_render
def render(ctx: PageContext) -> None:
    st.subheader("Clustering semántico")
    st.caption(
        "Agrupa licitaciones por similitud semántica. "
        "Útil para detectar patrones y nichos de mercado sin filtrar manualmente."
    )

    df = ctx.df

    if len(df) < 10:
        empty_state("🧩", "Insuficientes datos", "Aplica menos filtros para ver el clustering.")
        return

    # ── Controles ────────────────────────────────────────────────────────
    col_cfg1, col_cfg2 = st.columns([2, 1])
    with col_cfg1:
        n_clusters = st.slider(
            "Número de clusters",
            min_value=3,
            max_value=min(20, len(df) // 5),
            value=min(8, len(df) // 5),
            help="Más clusters = más granularidad. Recomendado: 6-10 para datasets medianos.",
        )
    with col_cfg2:
        auto_k = st.toggle(
            "Auto-optimizar k",
            value=False,
            help="Calcula el número óptimo de clusters via silhouette score (más lento).",
        )

    if st.button("🔄 Recalcular clusters", type="primary"):
        cluster_licitaciones.clear()

    # ── Calcular ─────────────────────────────────────────────────────────
    with st.spinner("Calculando clusters…"):
        try:
            clustered = cluster_licitaciones(df, n_clusters=n_clusters, auto_k=auto_k)
        except Exception as exc:
            st.error(f"Error al calcular clusters: {exc}")
            return

    k_actual = clustered["cluster_id"].nunique()
    st.caption(f"{k_actual} clusters detectados sobre {len(clustered):,} licitaciones")

    # ── Resumen por cluster ───────────────────────────────────────────────
    st.markdown("#### Resumen por cluster")
    summary = cluster_summary(clustered)
    if not summary.empty:
        fig_bar = px.bar(
            summary,
            x="cluster_label",
            y="n",
            color="cluster_id",
            template=ctx.plotly_template,
            labels={"cluster_label": "Cluster (keywords)", "n": "Licitaciones", "cluster_id": "ID"},
            height=360,
            text="n",
        )
        fig_bar.update_traces(textposition="outside")
        fig_bar.update_layout(
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=False,
            xaxis_tickangle=-30,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        # Tabla resumen
        data_table(
            summary.rename(
                columns={
                    "cluster_id": "ID",
                    "cluster_label": "Keywords",
                    "n": "Licitaciones",
                    "importe_medio": "Importe medio (€)",
                    "importe_total": "Importe total (€)",
                }
            ),
            height=260,
        )

    # ── Scatter por importe y cluster ────────────────────────────────────
    st.markdown("#### Distribución de importe por cluster")
    plot_df = clustered[clustered["importe"].notna()].copy()
    if not plot_df.empty:
        max_plot_rows = 5000
        if len(plot_df) > max_plot_rows:
            plot_df = plot_df.sample(n=max_plot_rows, random_state=42)
            st.caption(
                f"Mostrando muestra aleatoria de {max_plot_rows:,} filas "
                f"de {len(clustered[clustered['importe'].notna()]):,} para acelerar el gráfico."
            )
        fig_box = px.box(
            plot_df,
            x="cluster_label",
            y="importe",
            color="cluster_id",
            template=ctx.plotly_template,
            labels={"cluster_label": "Cluster", "importe": "Importe (€)"},
            height=360,
            log_y=True,
        )
        fig_box.update_layout(
            margin=dict(t=10, b=10, l=10, r=10),
            showlegend=False,
            xaxis_tickangle=-30,
        )
        st.plotly_chart(fig_box, use_container_width=True)

    # ── Explorar cluster ──────────────────────────────────────────────────
    st.markdown("#### Explorar licitaciones de un cluster")
    cluster_options = sorted(clustered["cluster_id"].unique())
    # Pre-computar etiquetas O(n) una sola vez, no por cada opción del dropdown
    label_map = (
        clustered.drop_duplicates("cluster_id").set_index("cluster_id")["cluster_label"].to_dict()
    )
    selected_cid = st.selectbox(
        "Selecciona cluster",
        cluster_options,
        format_func=lambda cid: f"Cluster {cid}: {label_map.get(cid, '')}",
        key="cluster_explorer",
    )
    cluster_rows = clustered[clustered["cluster_id"] == selected_cid]
    st.caption(f"{len(cluster_rows):,} licitaciones en este cluster")
    cols_show = [
        c
        for c in ["titulo", "organo_contratacion", "importe", "ccaa", "estado_desc"]
        if c in cluster_rows.columns
    ]
    data_table(cluster_rows[cols_show].head(100), height=340)
