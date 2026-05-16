"""Página Calendario — heatmap de publicaciones por día/semana."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.states import empty_state, guarded_render
from dashboard.pages._base import PageContext


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    st.subheader("📅 Calendario de publicaciones")
    st.caption("Heatmap de licitaciones publicadas por semana del año y día de la semana.")

    if df.empty or df["fecha_publicacion"].isna().all():
        empty_state("calendar", "Sin datos de fechas", "Ajusta los filtros activos.")
        return

    # ── Prepare date column ────────────────────────────────────────────────
    dfc = df.copy()
    dfc["fecha"] = pd.to_datetime(dfc["fecha_publicacion"], errors="coerce")
    dfc = dfc.dropna(subset=["fecha"])

    # ── Year selector ─────────────────────────────────────────────────────
    years = sorted(dfc["fecha"].dt.year.unique(), reverse=True)
    selected_year = st.selectbox("Año", years, index=0)

    dfc = dfc[dfc["fecha"].dt.year == selected_year].copy()
    if dfc.empty:
        st.info(f"Sin licitaciones en {selected_year}.")
        return

    dfc["week"] = dfc["fecha"].dt.isocalendar().week.astype(int)
    dfc["dow"] = dfc["fecha"].dt.dayofweek  # 0=Mon…6=Sun

    # ── Aggregate ─────────────────────────────────────────────────────────
    agg = dfc.groupby(["week", "dow"]).size().reset_index(name="n")
    # Pivot: rows=dow (0-6), cols=week (1-53)
    pivot = agg.pivot(index="dow", columns="week", values="n").reindex(
        index=range(7), columns=range(1, 54)
    ).fillna(0)

    dow_labels = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=[f"S{w}" for w in pivot.columns],
            y=dow_labels,
            colorscale="Blues",
            showscale=True,
            hoverongaps=False,
            hovertemplate="Semana %{x} / %{y}: <b>%{z:.0f}</b> licitaciones<extra></extra>",
        )
    )
    fig.update_layout(
        template=ctx.plotly_template,
        height=300,
        margin=dict(l=0, r=0, t=30, b=0),
        xaxis_title="Semana del año",
        yaxis_title="",
        title=f"Heatmap de publicaciones {selected_year}",
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Monthly volume bars ───────────────────────────────────────────────
    dfc["mes"] = dfc["fecha"].dt.to_period("M").astype(str)
    mensual = dfc.groupby("mes").agg(
        n=("id_externo", "count"),
        importe=("importe", "sum"),
    ).reset_index()

    import plotly.express as px

    col1, col2 = st.columns(2)
    with col1:
        fig2 = px.bar(
            mensual, x="mes", y="n",
            template=ctx.plotly_template,
            color_discrete_sequence=ctx.color_sequence,
            labels={"mes": "Mes", "n": "Publicaciones"},
            title="Publicaciones / mes",
        )
        fig2.update_layout(height=280, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig2, use_container_width=True)

    with col2:
        fig3 = px.bar(
            mensual, x="mes", y="importe",
            template=ctx.plotly_template,
            color_discrete_sequence=ctx.color_sequence[1:],
            labels={"mes": "Mes", "importe": "Importe total (€)"},
            title="Importe total / mes",
        )
        fig3.update_layout(height=280, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig3, use_container_width=True)

    # ── Day-of-week summary ───────────────────────────────────────────────
    dow_agg = dfc.groupby("dow").size().reset_index(name="n")
    dow_agg["dia"] = dow_agg["dow"].map(dict(enumerate(dow_labels)))
    st.markdown("**Distribución por día de la semana**")
    fig4 = px.bar(
        dow_agg, x="dia", y="n",
        template=ctx.plotly_template,
        color_discrete_sequence=ctx.color_sequence[2:],
        labels={"dia": "Día", "n": "Publicaciones"},
    )
    fig4.update_layout(height=240, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig4, use_container_width=True)
