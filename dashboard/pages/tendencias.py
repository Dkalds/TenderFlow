"""Página Tendencias — evolución mensual, heatmap, histograma."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.cards import chart_card
from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state, guarded_render
from dashboard.forecast import forecast_volume
from dashboard.kpi_config import KPI_FORMULAS
from dashboard.pages._base import PageContext
from dashboard.stats import is_anomaly, kpi_sparkline_series, mes_pico, yoy_delta
from dashboard.utils.format import fmt_eur


@st.fragment
def _render_evolution_charts(ctx: PageContext) -> None:
    """Gráficos de evolución mensual, heatmap, waterfall e histograma.

    Decorado con ``@st.fragment`` para re-renderizarse de forma
    independiente sin forzar un rerun completo de la página cuando
    cambia un filtro de la barra lateral.
    """
    df = ctx.df

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
        return

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
        fig.update_traces(hovertemplate="<b>%{y}</b> licitaciones<br>%{x}<extra></extra>")
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
        fig.update_traces(hovertemplate="<b>%{y:,.0f} €</b><br>%{x}<extra></extra>")
        fig.update_yaxes(tickformat=",.0f")
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

    with chart_card(
        "Variación mensual (mes a mes)", subtitle="Incremento/decremento respecto al mes anterior"
    ):
        if not g.empty and len(g) >= 2:
            g_sorted = g.sort_values("mes")
            g_sorted["delta"] = g_sorted["n"].diff()
            g_sorted = g_sorted.dropna(subset=["delta"])
            if not g_sorted.empty:
                measures = ["relative"] * len(g_sorted)
                fig = go.Figure(
                    go.Waterfall(
                        x=g_sorted["mes"].dt.strftime("%Y-%m"),
                        y=g_sorted["delta"],
                        measure=measures,
                        increasing=dict(marker=dict(color="#86BC25")),
                        decreasing=dict(marker=dict(color="#E21836")),
                        connector=dict(line=dict(color="rgba(255,255,255,0.08)", width=1)),
                        textposition="outside",
                        text=[f"{int(v):+d}" for v in g_sorted["delta"]],
                    )
                )
                fig.update_layout(
                    template=ctx.plotly_template,
                    height=350,
                    margin=dict(t=20, b=10, l=10, r=10),
                )
                fig.update_yaxes(title="Δ Licitaciones")
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

    # Gráficos de evolución mensual — fragmento independiente
    _render_evolution_charts(ctx)

    # ── Previsión de volumen (ExponentialSmoothing / fallback lineal) ─────
    with chart_card(
        "Previsión de licitaciones (6 meses)",
        subtitle="Proyección basada en suavizado exponencial. Banda = ±1.5σ histórico.",
    ):
        fc = forecast_volume(ctx.df_full, months_ahead=6, metric="count")
        if fc.empty:
            st.info("Datos insuficientes para generar previsión (mínimo 3 meses de histórico).")
        else:
            hist_fc = fc[fc["tipo"] == "histórico"]
            fcast = fc[fc["tipo"] == "forecast"]
            fig_fc = go.Figure()
            fig_fc.add_trace(
                go.Scatter(
                    x=hist_fc["mes"],
                    y=hist_fc["valor"],
                    mode="lines+markers",
                    name="Histórico",
                    line=dict(color="#86BC25", width=2),
                    marker=dict(size=5),
                )
            )
            if not fcast.empty:
                # Banda de confianza
                fig_fc.add_trace(
                    go.Scatter(
                        x=pd.concat([fcast["mes"], fcast["mes"].iloc[::-1]]),
                        y=pd.concat([fcast["upper"], fcast["lower"].iloc[::-1]]),
                        fill="toself",
                        fillcolor="rgba(0,163,224,0.15)",
                        line=dict(color="rgba(0,0,0,0)"),
                        name="Banda ±1.5σ",
                        showlegend=True,
                    )
                )
                fig_fc.add_trace(
                    go.Scatter(
                        x=fcast["mes"],
                        y=fcast["valor"],
                        mode="lines+markers",
                        name="Previsión",
                        line=dict(color="#00A3E0", width=2, dash="dash"),
                        marker=dict(size=6, symbol="diamond"),
                    )
                )
            fig_fc.update_layout(
                template=ctx.plotly_template,
                height=340,
                margin=dict(t=20, b=10, l=10, r=10),
                yaxis=dict(title="Nº licitaciones"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
            )
            st.plotly_chart(fig_fc, use_container_width=True)
