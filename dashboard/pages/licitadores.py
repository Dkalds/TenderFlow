"""Página Licitadores — ranking de empresas adjudicatarias recurrentes."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from config import settings
from dashboard.components.states import empty_state, guarded_render
from dashboard.normalize import normalize_company
from dashboard.pages._base import PageContext
from dashboard.utils.format import fmt_eur
from services.adjudicaciones import load_licitadores as svc_load_licitadores


@st.cache_data(ttl=settings.DASHBOARD_CACHE_TTL or None)
def _load_adjudicaciones(ccaa_filter: tuple[str, ...] | None = None) -> pd.DataFrame:
    """Carga adjudicaciones con datos de la licitación asociada.

    Si ``ccaa_filter`` se proporciona, push-down del WHERE a SQL (reduce I/O).
    Normaliza nombres y tipos numéricos dentro de la capa cacheada para evitar
    recalcularlo en cada rerun.
    """
    rows = svc_load_licitadores(ccaa_filter=ccaa_filter)
    df = pd.DataFrame(rows)

    if df.empty:
        return df

    # Pre-calcular columnas derivadas dentro de la capa cacheada
    df["nombre_norm"] = df["nombre"].apply(normalize_company)
    df["importe"] = pd.to_numeric(df["importe_adjudicado"], errors="coerce").fillna(0)
    return df


@guarded_render
def render(ctx: PageContext) -> None:
    st.subheader("🏆 Licitadores recurrentes")
    st.caption(
        "Empresas adjudicatarias del corpus. Ranking por importe, "
        "cuota de mercado y análisis de competencia."
    )

    df_adj = _load_adjudicaciones()

    if df_adj.empty:
        empty_state(
            "trophy",
            "Sin datos de adjudicaciones",
            "Las adjudicaciones se importan automáticamente con el pipeline diario.",
        )
        return

    # ── Global filters ─────────────────────────────────────────────────────
    ccaas = ["Todas", *sorted(df_adj["ccaa"].dropna().unique().tolist())]
    cpvs = ["Todos", *sorted(df_adj["cpv"].dropna().unique().tolist())]

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        sel_ccaa = st.selectbox("CCAA", ccaas)
    with col_f2:
        sel_cpv = st.selectbox("CPV", cpvs)

    dff = df_adj.copy()
    if sel_ccaa != "Todas":
        dff = dff[dff["ccaa"] == sel_ccaa]
    if sel_cpv != "Todos":
        dff = dff[dff["cpv"] == sel_cpv]

    if dff.empty:
        st.info("Sin datos para los filtros seleccionados.")
        return

    # ── KPI row ───────────────────────────────────────────────────────────
    total_importe = dff["importe"].sum()
    total_adj = len(dff)
    total_empresas = dff["nombre_norm"].nunique()
    pyme_pct = 100 * dff["es_pyme"].eq(1).sum() / max(1, dff["es_pyme"].notna().sum())

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Adjudicaciones", f"{total_adj:,}")
    k2.metric("Empresas únicas", f"{total_empresas:,}")
    k3.metric("Importe total", fmt_eur(total_importe))
    k4.metric("% PYME", f"{pyme_pct:.1f}%")

    st.markdown("---")

    # ── Ranking por importe ───────────────────────────────────────────────
    ranking = (
        dff.groupby("nombre_norm")
        .agg(
            n_adj=("id", "count"),
            importe_total=("importe", "sum"),
            importe_medio=("importe", "mean"),
            n_organos=("organo_contratacion", "nunique"),
            pyme_flag=("es_pyme", lambda x: int(x.eq(1).any())),
        )
        .sort_values("importe_total", ascending=False)
        .reset_index()
    )
    ranking["cuota_pct"] = 100 * ranking["importe_total"] / max(total_importe, 1)

    tab1, tab2, tab3 = st.tabs(["📊 Ranking", "🗺 Geografía", "📈 Evolución"])

    with tab1:
        top_n = st.slider("Top empresas", 5, 50, 20)
        top = ranking.head(top_n)

        fig = px.bar(
            top,
            x="importe_total",
            y="nombre_norm",
            orientation="h",
            color="cuota_pct",
            color_continuous_scale="Blues",
            template=ctx.plotly_template,
            labels={
                "importe_total": "Importe adjudicado (€)",
                "nombre_norm": "Empresa",
                "cuota_pct": "Cuota (%)",
            },
            title=f"Top {top_n} empresas por importe adjudicado",
            hover_data={"n_adj": True, "n_organos": True, "pyme_flag": False},
        )
        fig.update_layout(height=80 + 28 * top_n, margin=dict(l=0, r=20, t=40, b=0))
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            top[["nombre_norm", "n_adj", "importe_total", "cuota_pct", "n_organos"]]
            .rename(
                columns={
                    "nombre_norm": "Empresa",
                    "n_adj": "Adj.",
                    "importe_total": "Importe (€)",
                    "cuota_pct": "Cuota %",
                    "n_organos": "Órganos",
                }
            )
            .style.format({"Importe (€)": "{:,.0f}", "Cuota %": "{:.1f}"}),
            use_container_width=True,
            height=350,
        )

    with tab2:
        geo = (
            dff.groupby("ccaa")
            .agg(n=("id", "count"), importe=("importe", "sum"))
            .reset_index()
            .sort_values("importe", ascending=False)
        )
        if not geo.empty:
            fig2 = px.bar(
                geo,
                x="importe",
                y="ccaa",
                orientation="h",
                template=ctx.plotly_template,
                color_discrete_sequence=ctx.color_sequence,
                labels={"importe": "Importe (€)", "ccaa": "CCAA", "n": "Adj."},
                title="Adjudicaciones por CCAA",
            )
            fig2.update_layout(height=350, margin=dict(l=0, r=20, t=40, b=0))
            st.plotly_chart(fig2, use_container_width=True)

    with tab3:
        dff2 = dff.copy()
        dff2["fecha"] = pd.to_datetime(dff2["fecha_adjudicacion"], errors="coerce")
        dff2 = dff2.dropna(subset=["fecha"])
        if not dff2.empty:
            dff2["mes"] = dff2["fecha"].dt.to_period("M").astype(str)
            evol = (
                dff2.groupby("mes").agg(n=("id", "count"), importe=("importe", "sum")).reset_index()
            )
            fig3 = px.line(
                evol,
                x="mes",
                y="importe",
                template=ctx.plotly_template,
                color_discrete_sequence=ctx.color_sequence,
                labels={"mes": "Mes", "importe": "Importe (€)"},
                title="Evolución mensual de adjudicaciones",
                markers=True,
            )
            fig3.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("Sin fechas de adjudicación disponibles.")
