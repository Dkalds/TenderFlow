"""Página Tendencias CPV — evolución y predicción de precios por código CPV."""

from __future__ import annotations

import warnings

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.states import empty_state, guarded_render
from dashboard.pages._base import PageContext
from dashboard.utils.format import fmt_eur


def _arima_forecast(series: pd.Series, steps: int = 6) -> pd.Series | None:
    """Intenta ajustar ARIMA(1,1,1) y devuelve predicción; None si falla."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from statsmodels.tsa.arima.model import ARIMA  # type: ignore[import]

            model = ARIMA(series, order=(1, 1, 1))
            fit = model.fit()
            fc = fit.forecast(steps=steps)
            return fc.clip(lower=0)
    except Exception:
        return None


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    st.subheader("📊 Tendencias de precios por CPV")
    st.caption(
        "Serie temporal de importes medianos/percentiles por código CPV. "
        "Predicción ARIMA opcional (requiere statsmodels)."
    )

    if df.empty:
        empty_state("chart", "Sin datos disponibles", "Ajusta los filtros activos.")
        return

    dfc = df[df["importe"].notna() & df["cpv"].notna()].copy()
    if dfc.empty:
        st.info("Sin licitaciones con importe y CPV definidos en los filtros activos.")
        return

    dfc["fecha"] = pd.to_datetime(dfc["fecha_publicacion"], errors="coerce")
    dfc = dfc.dropna(subset=["fecha"])

    # ── CPV selector ───────────────────────────────────────────────────────
    cpv_counts = dfc["cpv"].value_counts()
    cpv_options = cpv_counts[cpv_counts >= 3].index.tolist()  # need ≥3 data points
    if not cpv_options:
        st.info("Se necesitan al menos 3 licitaciones por CPV para generar tendencias.")
        return

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_cpv = st.selectbox(
            "Código CPV",
            cpv_options,
            format_func=lambda c: f"{c} ({cpv_counts.get(c, 0)} licitaciones)",
        )
    with col2:
        freq = st.selectbox("Agrupación", ["Trimestral", "Mensual", "Anual"], index=0)

    freq_map = {"Mensual": "ME", "Trimestral": "QE", "Anual": "YE"}
    pd_freq = freq_map[freq]

    # ── Aggregate ─────────────────────────────────────────────────────────
    dfc_cpv = dfc[dfc["cpv"] == selected_cpv].copy()
    dfc_cpv = dfc_cpv.set_index("fecha").sort_index()

    agg = dfc_cpv["importe"].resample(pd_freq).agg(
        mediana=("median"),
        p25=lambda x: x.quantile(0.25),
        p75=lambda x: x.quantile(0.75),
        n="count",
        total="sum",
    ).dropna(how="all")

    if agg.empty:
        st.info("Datos insuficientes para el período seleccionado.")
        return

    # ── Main chart ────────────────────────────────────────────────────────
    fig = go.Figure()

    # P25-P75 band
    fig.add_trace(
        go.Scatter(
            x=list(agg.index) + list(agg.index[::-1]),
            y=list(agg["p75"]) + list(agg["p25"][::-1]),
            fill="toself",
            fillcolor="rgba(99,110,250,0.15)",
            line=dict(color="rgba(255,255,255,0)"),
            name="P25–P75",
            hoverinfo="skip",
        )
    )

    # Median line
    fig.add_trace(
        go.Scatter(
            x=agg.index,
            y=agg["mediana"],
            mode="lines+markers",
            name="Mediana",
            line=dict(color=ctx.color_sequence[0], width=2),
            hovertemplate="%{x|%Y-%m}: <b>%{y:,.0f} €</b><extra></extra>",
        )
    )

    # ── ARIMA forecast ─────────────────────────────────────────────────────
    show_forecast = st.toggle("Mostrar predicción ARIMA", value=False)
    if show_forecast and len(agg) >= 6:
        fc = _arima_forecast(agg["mediana"].dropna(), steps=4)
        if fc is not None:
            fig.add_trace(
                go.Scatter(
                    x=fc.index,
                    y=fc.values,
                    mode="lines+markers",
                    name="Predicción",
                    line=dict(color=ctx.color_sequence[1], width=2, dash="dot"),
                    hovertemplate="%{x|%Y-%m}: <b>%{y:,.0f} €</b> (pred.)<extra></extra>",
                )
            )
        else:
            st.caption("⚠ statsmodels no disponible — instala con `pip install statsmodels`.")

    fig.update_layout(
        template=ctx.plotly_template,
        height=400,
        margin=dict(l=0, r=0, t=30, b=0),
        yaxis_title="Importe (€)",
        xaxis_title="",
        title=f"CPV {selected_cpv} — Evolución de importes",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Stats table ───────────────────────────────────────────────────────
    with st.expander("Tabla de datos"):
        agg_show = agg.copy()
        for col in ["mediana", "p25", "p75", "total"]:
            agg_show[col] = agg_show[col].apply(lambda x: fmt_eur(x) if pd.notna(x) else "—")
        agg_show.index = agg_show.index.strftime("%Y-%m")
        st.dataframe(agg_show, use_container_width=True)

    # ── CPV landscape ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("**Top CPV por importe total (filtros activos)**")
    top_cpv = (
        dfc.groupby("cpv")["importe"]
        .agg(total="sum", n="count", mediana="median")
        .nlargest(15, "total")
        .reset_index()
    )
    if not top_cpv.empty:
        fig2 = px.bar(
            top_cpv,
            x="total",
            y="cpv",
            orientation="h",
            template=ctx.plotly_template,
            color="mediana",
            color_continuous_scale="Blues",
            labels={"total": "Importe total (€)", "cpv": "CPV", "mediana": "Mediana"},
            title="Top 15 CPV por importe acumulado",
        )
        fig2.update_layout(height=420, margin=dict(l=0, r=20, t=40, b=0))
        st.plotly_chart(fig2, use_container_width=True)
