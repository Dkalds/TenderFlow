"""Página Proyectos & Módulos — módulos SAP, sunburst, CPV."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from dashboard.components.cards import chart_card
from dashboard.components.kpi import kpi_card
from dashboard.components.states import guarded_render
from dashboard.components.tables import data_table
from dashboard.kpi_config import KPI_FORMULAS
from dashboard.pages._base import PageContext
from dashboard.stats import (
    importe_medio_por_modulo,
    pct_multi_modulo,
    portfolio_match,
    ticket_medio_por_plataforma,
    top_modulo_yoy,
)
from dashboard.utils.format import fmt_eur


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    # ── Perfil SAP — KPIs comerciales específicos ─────────────────
    st.subheader("Perfil SAP")
    _render_perfil_sap(df)

    st.markdown("")

    cMod, cType = st.columns(2)

    with cMod:
        with chart_card("Módulos / productos SAP detectados"):
            mod_df = df.explode("modulos")
            mod_count = (
                mod_df.groupby("modulos")
                .agg(n=("id_externo", "count"), importe=("importe", "sum"))
                .reset_index()
                .sort_values("n", ascending=False)
            )
            if not mod_count.empty:
                fig = px.bar(
                    mod_count.head(15).sort_values("n"),
                    x="n",
                    y="modulos",
                    orientation="h",
                    template=ctx.plotly_template,
                    color="importe",
                    color_continuous_scale="YlGn",
                    labels={"n": "Apariciones", "modulos": "", "importe": "Importe €"},
                )
                fig.update_layout(height=520, margin=dict(t=20, b=10, l=10, r=10))
                st.plotly_chart(fig, use_container_width=True)

    with cType:
        with chart_card("Tipo de proyecto × Estado"):
            cross = df.groupby(["tipo_proyecto", "estado_desc"]).size().reset_index(name="n")
            if not cross.empty:
                fig = px.sunburst(
                    cross,
                    path=["tipo_proyecto", "estado_desc"],
                    values="n",
                    template=ctx.plotly_template,
                    color="n",
                    color_continuous_scale="Greens",
                )
                fig.update_layout(height=520, margin=dict(t=20, b=10, l=10, r=10))
                st.plotly_chart(fig, use_container_width=True)

    # ── Importe medio por módulo ─────────────────────────────────
    st.subheader("Importe medio por módulo SAP")
    imp_mod = importe_medio_por_modulo(df)
    if not imp_mod.empty:
        imp_mod_top = imp_mod.head(15).rename(
            columns={
                "modulo": "Módulo",
                "n": "Lic.",
                "importe_medio": "Importe medio €",
                "importe_total": "Importe total €",
            }
        )
        n_max_mod = int(imp_mod_top["Lic."].max()) or 1
        data_table(
            imp_mod_top,
            column_config={
                "Lic.": st.column_config.ProgressColumn(
                    "Lic.", min_value=0, max_value=n_max_mod, format="%d"
                ),
                "Importe medio €": st.column_config.NumberColumn(format="%.0f €"),
                "Importe total €": st.column_config.NumberColumn(format="%.0f €"),
            },
        )

    st.subheader("Top códigos CPV")
    cpv_df = (
        df.groupby(["cpv", "cpv_desc"])
        .agg(n=("id_externo", "count"), importe=("importe", "sum"))
        .reset_index()
        .sort_values("n", ascending=False)
        .head(15)
    )
    if not cpv_df.empty:
        cpv_table = cpv_df.rename(
            columns={"cpv_desc": "CPV", "n": "Lic.", "importe": "Importe €"}
        )[["CPV", "Lic.", "Importe €"]]
        n_max_cpv = int(cpv_table["Lic."].max()) or 1
        data_table(
            cpv_table,
            column_config={
                "Lic.": st.column_config.ProgressColumn(
                    "Lic.", min_value=0, max_value=n_max_cpv, format="%d"
                ),
                "Importe €": st.column_config.NumberColumn(format="%.0f €"),
            },
        )


def _render_perfil_sap(df) -> None:
    """4 KPIs comerciales específicos de SAP: ticket medio, módulo YoY, multi-módulo, portfolio."""
    # 1. Importe medio de licitaciones con algún módulo SAP
    imp_mod_df = importe_medio_por_modulo(df)
    if not imp_mod_df.empty:
        # Importe medio "global" ponderado por número de apariciones
        peso = (imp_mod_df["importe_medio"] * imp_mod_df["n"]).sum()
        total_n = imp_mod_df["n"].sum()
        imp_medio_sap = (peso / total_n) if total_n else 0
    else:
        imp_medio_sap = 0

    # 2. Top módulo YoY
    top_yoy = top_modulo_yoy(df)

    # 3. % Multi-módulo
    pct_multi = pct_multi_modulo(df)

    # 4. Ticket S/4HANA
    plataformas = ticket_medio_por_plataforma(df)
    s4 = plataformas["s4hana"]

    # 5. Portfolio match
    pct_port = portfolio_match(df)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.markdown(
            kpi_card(
                "Ticket medio SAP",
                fmt_eur(imp_medio_sap),
                delta="lics con módulo detectado",
                icon="💼",
                tooltip=KPI_FORMULAS["importe_medio_modulo"],
            ),
            unsafe_allow_html=True,
        )
    with c2:
        if top_yoy:
            pct_str = (
                f"+{top_yoy['crecimiento_pct']:.0f}%"
                if top_yoy["crecimiento_pct"] < 999
                else "NUEVO"
            )
            st.markdown(
                kpi_card(
                    "Top módulo YoY",
                    str(top_yoy["modulo"]),
                    delta=f"{pct_str} · {top_yoy['n_act']} lics",
                    delta_up=True,
                    icon="🚀",
                    tooltip=KPI_FORMULAS["top_modulo_yoy"],
                ),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                kpi_card("Top módulo YoY", "—", icon="🚀"),
                unsafe_allow_html=True,
            )
    with c3:
        st.markdown(
            kpi_card(
                "% Multi-módulo",
                f"{pct_multi:.0f}%",
                delta="≥2 módulos detectados",
                delta_up=pct_multi >= 30,
                icon="🧩",
                tooltip=KPI_FORMULAS["pct_multi_modulo"],
            ),
            unsafe_allow_html=True,
        )
    with c4:
        if s4["n"] > 0:
            st.markdown(
                kpi_card(
                    "Ticket S/4HANA",
                    fmt_eur(s4["ticket_medio"]),
                    delta=f"{s4['n']} lics",
                    icon="⚡",
                    tooltip=KPI_FORMULAS["ticket_s4hana"],
                ),
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                kpi_card("Ticket S/4HANA", "—", delta="sin menciones", icon="⚡"),
                unsafe_allow_html=True,
            )
    with c5:
        st.markdown(
            kpi_card(
                "% Match portfolio",
                f"{pct_port:.0f}%",
                delta="servicios propios",
                delta_up=pct_port >= 40,
                icon="🎯",
                tooltip=KPI_FORMULAS["portfolio_match"],
            ),
            unsafe_allow_html=True,
        )
