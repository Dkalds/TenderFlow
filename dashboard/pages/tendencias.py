"""Página Tendencias — evolución mensual, heatmap, histograma."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.components.cards import chart_card
from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state, guarded_render
from dashboard.kpi_config import KPI_FORMULAS
from dashboard.pages._base import PageContext
from dashboard.stats import is_anomaly, kpi_sparkline_series, mes_pico, yoy_delta
from dashboard.utils.format import fmt_eur


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    # ── KPIs de tendencia ─────────────────────────────────────────
    if not df.empty and df["fecha_publicacion"].notna().any():
        # Sparklines semanales (12 últimas semanas)
        sp_count = kpi_sparkline_series(df, metric="count", freq="W", periods=12)
        sp_sum = kpi_sparkline_series(df, metric="sum", freq="W", periods=12)

        k1, k2, k3, k4 = st.columns(4)

        # Δ licitaciones últimos 30d vs 30d anteriores
        v_act, _v_prev, pct_n = yoy_delta(df, col="importe", agg="count", days=30)
        # Anomaly: la última semana vs 11 anteriores
        anom_n = is_anomaly(sp_count[-1], sp_count[:-1]) if len(sp_count) >= 4 else False
        with k1:
            st.markdown(
                kpi_card(
                    "Licitaciones (30d)",
                    f"{int(v_act):,}",
                    delta=f"{pct_n:+.1f}% vs 30d anteriores",
                    delta_up=pct_n >= 0,
                    icon="📈",
                    sparkline=sp_count,
                    anomaly=anom_n,
                    tooltip=KPI_FORMULAS["licitaciones_30d"],
                ),
                unsafe_allow_html=True,
            )

        # Δ importe últimos 30d vs 30d anteriores
        v_imp, _, pct_imp = yoy_delta(df, col="importe", agg="sum", days=30)
        anom_imp = is_anomaly(sp_sum[-1], sp_sum[:-1]) if len(sp_sum) >= 4 else False
        with k2:
            st.markdown(
                kpi_card(
                    "Importe (30d)",
                    fmt_eur(v_imp),
                    delta=f"{pct_imp:+.1f}% vs 30d anteriores",
                    delta_up=pct_imp >= 0,
                    icon="💶",
                    sparkline=sp_sum,
                    anomaly=anom_imp,
                    tooltip=KPI_FORMULAS["importe_30d"],
                ),
                unsafe_allow_html=True,
            )

        # Crecimiento YoY (365d vs 365d anteriores) — en nº de licitaciones
        _, _, pct_y = yoy_delta(df, col="importe", agg="count", days=365)
        with k3:
            st.markdown(
                kpi_card(
                    "Crecimiento YoY (lics)",
                    f"{pct_y:+.1f}%",
                    delta="nº lics últimos 12m vs anteriores 12m",
                    delta_up=pct_y >= 0,
                    icon="🚀",
                    tooltip=KPI_FORMULAS["yoy_365d"],
                ),
                unsafe_allow_html=True,
            )

        # Mes pico
        mp = mes_pico(df)
        if mp:
            with k4:
                st.markdown(
                    kpi_card(
                        "Mes pico",
                        mp["mes"],
                        delta=f"{fmt_eur(mp['importe'])} · {mp['n']} lics",
                        icon="🔝",
                        tooltip=KPI_FORMULAS["mes_pico"],
                    ),
                    unsafe_allow_html=True,
                )

        st.markdown("")

    g = (
        df.dropna(subset=["mes"])
        .groupby("mes")
        .agg(n=("id_externo", "count"), importe=("importe", "sum"))
        .reset_index()
    )

    if g.empty:
        empty_state(
            "📊",
            "Sin datos de evolución mensual",
            "No hay licitaciones con fecha de publicación en el rango seleccionado.",
        )
    else:
        c1, c2 = st.columns(2)
        with c1, chart_card("Licitaciones por mes"):
            fig = px.bar(
                g,
                x="mes",
                y="n",
                template=ctx.plotly_template,
                labels={"mes": "Mes", "n": "Nº licitaciones"},
                color_discrete_sequence=["#86BC25"],
            )
            fig.update_layout(height=380, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        with c2, chart_card("Importe acumulado por mes"):
            fig = px.area(
                g,
                x="mes",
                y="importe",
                template=ctx.plotly_template,
                labels={"mes": "Mes", "importe": "Importe (€)"},
                color_discrete_sequence=["#00A3E0"],
            )
            fig.update_layout(height=380, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

    with chart_card("Heatmap mes × estado"):
        if not df.empty and df["mes"].notna().any():
            hm = (
                df.dropna(subset=["mes"])
                .groupby([df["mes"].dt.strftime("%Y-%m"), "estado_desc"])
                .size()
                .reset_index(name="n")
            )
            hm.columns = pd.Index(["mes", "estado", "n"])
            pivot = hm.pivot(index="estado", columns="mes", values="n").fillna(0)
            fig = px.imshow(
                pivot,
                aspect="auto",
                template=ctx.plotly_template,
                color_continuous_scale="Greens",
                labels=dict(color="Licitaciones"),
            )
            fig.update_layout(height=350, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

    with chart_card("Distribución de importes", subtitle="Escala logarítmica"):
        if df["importe"].notna().any():
            fig = px.histogram(
                df.dropna(subset=["importe"]).assign(
                    importe_log=lambda x: x["importe"].clip(lower=1)
                ),
                x="importe_log",
                log_x=True,
                nbins=40,
                template=ctx.plotly_template,
                color_discrete_sequence=["#86BC25"],
                labels={"importe_log": "Importe (€, log)"},
            )
            fig.update_layout(height=320, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
