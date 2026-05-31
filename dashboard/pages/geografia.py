"""Página Geografía — reparto por CCAA y provincias."""

from __future__ import annotations

import plotly.express as px
import streamlit as st

from dashboard.components.cards import chart_card
from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state, guarded_render
from dashboard.components.tables import data_table
from dashboard.pages._base import PageContext
from dashboard.stats import ccaa_mas_activa, concentracion_geografica
from dashboard.utils.format import fmt_eur
from dashboard.utils.geo import load_spain_ccaa_geojson


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    _geo_src = df.dropna(subset=["ccaa"])
    _count_col = "id_externo" if "id_externo" in _geo_src.columns else "importe"
    geo = (
        _geo_src.groupby("ccaa")
        .agg(n=(_count_col, "count"), importe=("importe", "sum"))
        .reset_index()
    )

    # ── KPIs geográficos ─────────────────────────────────────────
    if not geo.empty:
        activa = ccaa_mas_activa(df)
        conc_top3 = concentracion_geografica(df, top_n=3)

        # CCAA con ticket medio más alto
        geo_ticket = geo.assign(ticket=lambda x: x["importe"] / x["n"].clip(lower=1))
        geo_ticket = geo_ticket[geo_ticket["n"] >= 5]  # mínimo 5 lic. para ser significativo
        ticket_top = (
            geo_ticket.sort_values("ticket", ascending=False).head(1)
            if not geo_ticket.empty
            else None
        )

        kG1, kG2, kG3 = st.columns(3)
        if activa:
            with kG1:
                st.markdown(
                    kpi_card(
                        "CCAA más activa",
                        str(activa["ccaa"])[:20],
                        delta=f"{activa['n']:,} licitaciones · {fmt_eur(float(activa['importe']))}",
                        icon="🗺️",
                    ),
                    unsafe_allow_html=True,
                )
        if ticket_top is not None and not ticket_top.empty:
            t_row = ticket_top.iloc[0]
            with kG2:
                st.markdown(
                    kpi_card(
                        "CCAA mayor ticket",
                        str(t_row["ccaa"])[:20],
                        delta=f"Ticket medio {fmt_eur(t_row['ticket'])}",
                        icon="💎",
                    ),
                    unsafe_allow_html=True,
                )
        with kG3:
            st.markdown(
                kpi_card(
                    "Concentración top-3",
                    f"{conc_top3:.0f}%",
                    delta="del importe total",
                    delta_up=conc_top3 < 60,
                    icon="📍",
                ),
                unsafe_allow_html=True,
            )

        st.markdown("")

    # ── Mapa coroplético de CCAA ──────────────────────────────────
    geojson = load_spain_ccaa_geojson()
    if geojson is not None and not geo.empty:
        with chart_card("Mapa por Comunidad Autónoma"):
            map_metric = st.radio(
                "Métrica del mapa",
                ["Licitaciones", "Importe €"],
                horizontal=True,
                label_visibility="collapsed",
                key="geo_map_metric",
            )
            value_col = "n" if map_metric == "Licitaciones" else "importe"
            fig_map = px.choropleth_mapbox(
                geo,
                geojson=geojson,
                locations="ccaa",
                featureidkey="properties.name",
                color=value_col,
                color_continuous_scale="Greens",
                mapbox_style="carto-darkmatter",
                center={"lat": 40.0, "lon": -3.7},
                zoom=4.3,
                labels={"n": "Licitaciones", "importe": "Importe €", "ccaa": "CCAA"},
                hover_data={"n": True, "importe": ":,.0f"},
            )
            fig_map.update_layout(
                height=500,
                margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(fig_map, use_container_width=True)
    elif geojson is None and not geo.empty:
        with chart_card("Mapa por Comunidad Autónoma"):
            empty_state(
                "🗺️",
                "Mapa no disponible",
                "No se pudo cargar el GeoJSON de CCAA. Revisa la conexión a internet.",
            )

    st.markdown("")

    cM, cT = st.columns([2, 1])
    with cM, chart_card("Reparto por Comunidad Autónoma"):
        if not geo.empty:
            fig = px.bar(
                geo.sort_values("n"),
                x="n",
                y="ccaa",
                orientation="h",
                template=ctx.plotly_template,
                color="importe",
                color_continuous_scale="Greens",
                labels={"n": "Licitaciones", "ccaa": "", "importe": "Importe €"},
            )
            fig.update_layout(height=600, margin=dict(t=20, b=10, l=10, r=10))
            fig.update_xaxes(tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True)
        else:
            empty_state(
                "🗺️",
                "Sin datos geográficos",
                "Re-ejecuta el pipeline tras la actualización del parser para poblar CCAA y provincias.",
            )

    with cT:
        prov_src = df.dropna(subset=["provincia"])
        _count_col_p = "id_externo" if "id_externo" in prov_src.columns else "importe"
        prov = (
            prov_src.groupby("provincia")
            .agg(n=(_count_col_p, "count"), importe=("importe", "sum"))
            .reset_index()
            .sort_values("n", ascending=False)
            .head(15)
        )
        with chart_card("Top provincias"):
            if not prov.empty:
                n_max = int(prov["n"].max()) or 1
                data_table(
                    prov.rename(columns={"n": "Lic.", "importe": "Importe €"}),
                    column_config={
                        "Lic.": st.column_config.ProgressColumn(
                            "Lic.", min_value=0, max_value=n_max, format="%d"
                        ),
                        "Importe €": st.column_config.NumberColumn("Importe €", format="%.0f €"),
                    },
                )
