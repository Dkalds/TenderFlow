"""Sub-sección de UTEs (Uniones Temporales de Empresas) para la página Competidores."""

from __future__ import annotations

from collections import Counter
from itertools import combinations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state
from dashboard.components.tables import data_table
from dashboard.normalize import parse_ute_members
from dashboard.pages._base import PageContext
from dashboard.utils.format import fmt_eur


def render_utes_section(ctx: PageContext, adj_ci: pd.DataFrame) -> None:
    """Sub-apartado dedicado al análisis de UTEs dentro de Competencia."""
    st.divider()
    st.subheader("🤝 UTEs — Uniones Temporales de Empresas")
    st.caption(
        "Análisis de contratos adjudicados a uniones temporales: qué empresas "
        "suelen aliarse, en qué tipo de contratos y con qué resultado."
    )

    utes = adj_ci[adj_ci["es_ute"].fillna(False)].copy()
    if utes.empty:
        empty_state(
            "🤝",
            "Sin UTEs en el rango filtrado",
            "Ninguna adjudicación corresponde a una Unión Temporal con los filtros activos.",
        )
        return

    # Parseo de miembros y métricas derivadas
    utes["miembros"] = utes["nombre"].apply(parse_ute_members)
    utes["n_miembros"] = utes["miembros"].apply(len)
    utes_with_members = utes[utes["n_miembros"] > 0].copy()

    total_mercado = adj_ci["importe_adjudicado"].sum(skipna=True)
    total_ute = utes["importe_adjudicado"].sum(skipna=True)
    pct_mercado = (total_ute / total_mercado * 100) if total_mercado else 0.0
    empresas_unicas = {m for ms in utes_with_members["miembros"] for m in ms}

    # ── KPIs ─────────────────────────────────────────────────────
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            kpi_card(
                "Adjudicaciones en UTE",
                f"{len(utes):,}",
                delta=f"{len(utes) / max(len(adj_ci), 1) * 100:.1f}% del total",
                delta_up=True,
                icon="📑",
            ),
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            kpi_card(
                "Importe en UTE",
                fmt_eur(total_ute),
                delta=f"{pct_mercado:.1f}% del mercado",
                delta_up=True,
                icon="💶",
            ),
            unsafe_allow_html=True,
        )
    with k3:
        ticket_ute = utes["importe_adjudicado"].mean()
        ticket_no_ute = adj_ci.loc[~adj_ci["es_ute"].fillna(False), "importe_adjudicado"].mean()
        delta_ticket = (
            ((ticket_ute / ticket_no_ute - 1) * 100)
            if ticket_no_ute and pd.notna(ticket_no_ute) and ticket_no_ute > 0
            else 0
        )
        st.markdown(
            kpi_card(
                "Ticket medio en UTE",
                fmt_eur(ticket_ute) if pd.notna(ticket_ute) else "—",
                delta=f"{delta_ticket:+.0f}% vs solo",
                delta_up=delta_ticket >= 0,
                icon="🎫",
            ),
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            kpi_card(
                "Empresas distintas",
                f"{len(empresas_unicas):,}",
                delta="que han ido en UTE",
                delta_up=True,
                icon="🏢",
            ),
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── Top empresas que más participan en UTEs ──────────────────
    cU1, cU2 = st.columns(2)
    with cU1:
        st.subheader("Empresas más activas en UTE")
        st.caption("Nº de adjudicaciones en las que aparecen como miembro de la UTE.")
        if utes_with_members.empty:
            st.info("No se han podido extraer miembros de los nombres de UTE.")
        else:
            counter_emp: Counter[str] = Counter()
            importe_emp: dict[str, float] = {}
            for _, row in utes_with_members.iterrows():
                imp = (
                    float(row["importe_adjudicado"]) if pd.notna(row["importe_adjudicado"]) else 0.0
                )
                # Repartir importe a partes iguales entre los miembros
                share = imp / max(row["n_miembros"], 1)
                for m in row["miembros"]:
                    counter_emp[m] += 1
                    importe_emp[m] = importe_emp.get(m, 0.0) + share

            top_emp = counter_emp.most_common(15)
            top_df = pd.DataFrame(
                [
                    {
                        "empresa": e,
                        "participaciones": n,
                        "importe_atribuido": importe_emp.get(e, 0.0),
                    }
                    for e, n in top_emp
                ]
            )
            fig = px.bar(
                top_df.sort_values("participaciones"),
                x="participaciones",
                y="empresa",
                orientation="h",
                template=ctx.plotly_template,
                color="importe_atribuido",
                color_continuous_scale="Blues",
                labels={
                    "participaciones": "Nº participaciones",
                    "empresa": "",
                    "importe_atribuido": "Importe atribuido (€)",
                },
                hover_data={"importe_atribuido": ":,.0f"},
            )
            fig.update_layout(height=420, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

    with cU2:
        st.subheader("Parejas de socios más frecuentes")
        st.caption("Pares de empresas que coinciden en una misma UTE.")
        pair_counter: Counter[tuple[str, str]] = Counter()
        pair_importe: dict[tuple[str, str], float] = {}
        for _, row in utes_with_members.iterrows():
            ms = sorted(set(row["miembros"]))
            if len(ms) < 2:
                continue
            imp = float(row["importe_adjudicado"]) if pd.notna(row["importe_adjudicado"]) else 0.0
            for a, b in combinations(ms, 2):
                key = (a, b)
                pair_counter[key] += 1
                pair_importe[key] = pair_importe.get(key, 0.0) + imp

        if not pair_counter:
            st.info("No hay UTEs con ≥2 miembros parseables en el filtro actual.")
        else:
            top_pairs = pair_counter.most_common(15)
            pairs_df = pd.DataFrame(
                [
                    {
                        "pareja": f"{a[:25]} ↔ {b[:25]}",
                        "veces": n,
                        "importe": pair_importe.get((a, b), 0.0),
                    }
                    for (a, b), n in top_pairs
                ]
            )
            fig = px.bar(
                pairs_df.sort_values("veces"),
                x="veces",
                y="pareja",
                orientation="h",
                template=ctx.plotly_template,
                color="importe",
                color_continuous_scale="Purples",
                labels={"veces": "Co-ocurrencias", "pareja": "", "importe": "Importe total (€)"},
                hover_data={"importe": ":,.0f"},
            )
            fig.update_layout(height=420, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

    # ── UTE vs solo: comparativa de comportamiento ───────────────
    st.subheader("UTE vs adjudicación individual")
    sin_ute = adj_ci[~adj_ci["es_ute"].fillna(False)]
    comp_rows = []
    for label, sub in (("UTE", utes), ("Individual", sin_ute)):
        comp_rows.append(
            {
                "Tipo": label,
                "Contratos": len(sub),
                "Importe total": float(sub["importe_adjudicado"].sum(skipna=True)),
                "Ticket medio": float(sub["importe_adjudicado"].mean(skipna=True))
                if len(sub) > 0
                else 0.0,
                "Baja media (%)": float(sub["baja_pct"].mean(skipna=True))
                if "baja_pct" in sub
                else 0.0,
                "Ofertas medias": float(sub["n_ofertas_recibidas"].mean(skipna=True))
                if "n_ofertas_recibidas" in sub
                else 0.0,
            }
        )
    comp_df = pd.DataFrame(comp_rows)
    cC1, cC2 = st.columns([1, 1])
    with cC1:
        st.dataframe(
            comp_df.assign(
                **{
                    "Importe total": comp_df["Importe total"].apply(fmt_eur),
                    "Ticket medio": comp_df["Ticket medio"].apply(fmt_eur),
                    "Baja media (%)": comp_df["Baja media (%)"].round(2),
                    "Ofertas medias": comp_df["Ofertas medias"].round(2),
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
    with cC2:
        # Distribución de número de socios
        if not utes_with_members.empty:
            dist_socios = (
                utes_with_members.groupby("n_miembros")
                .agg(contratos=("id", "count"), importe=("importe_adjudicado", "sum"))
                .reset_index()
            )
            fig = px.bar(
                dist_socios,
                x="n_miembros",
                y="contratos",
                template=ctx.plotly_template,
                color="importe",
                color_continuous_scale="Teal",
                labels={
                    "n_miembros": "Nº de socios en la UTE",
                    "contratos": "Adjudicaciones",
                    "importe": "Importe (€)",
                },
                hover_data={"importe": ":,.0f"},
            )
            fig.update_layout(height=300, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

    # ── Evolución temporal ───────────────────────────────────────
    st.subheader("Evolución temporal de adjudicaciones en UTE")
    evo_ute = utes.dropna(subset=["fecha_adjudicacion"]).copy()
    if not evo_ute.empty:
        evo_ute["mes"] = evo_ute["fecha_adjudicacion"].dt.to_period("M").dt.to_timestamp()
        evo_g = (
            evo_ute.groupby("mes")
            .agg(contratos=("id", "count"), importe=("importe_adjudicado", "sum"))
            .reset_index()
        )
        fig = go.Figure()
        fig.add_bar(
            x=evo_g["mes"],
            y=evo_g["contratos"],
            name="Nº contratos",
            marker_color=ctx.color_sequence[0],
            yaxis="y",
        )
        fig.add_trace(
            go.Scatter(
                x=evo_g["mes"],
                y=evo_g["importe"],
                name="Importe (€)",
                mode="lines+markers",
                line=dict(color=ctx.color_sequence[1] if len(ctx.color_sequence) > 1 else "#888"),
                yaxis="y2",
            )
        )
        fig.update_layout(
            template=ctx.plotly_template,
            height=320,
            margin=dict(t=10, b=10, l=10, r=10),
            yaxis=dict(title="Nº contratos"),
            yaxis2=dict(title="Importe (€)", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Filtro por empresa miembro ───────────────────────────────
    st.subheader("Contratos por empresa miembro de UTE")
    if empresas_unicas:
        opciones_emp = sorted(empresas_unicas)
        emp_sel = st.multiselect(
            "Filtrar UTEs en las que aparezca alguna de estas empresas",
            options=opciones_emp,
            placeholder="Empieza a escribir el nombre normalizado…",
            key="ute_filter_empresas",
        )
        if emp_sel:
            sel_set = set(emp_sel)
            mask_emp = utes_with_members["miembros"].apply(lambda ms: any(m in sel_set for m in ms))
            utes_filtradas = utes_with_members[mask_emp].copy()
        else:
            utes_filtradas = utes.copy()
    else:
        utes_filtradas = utes.copy()

    if utes_filtradas.empty:
        st.info("Ninguna UTE coincide con el filtro.")
        return

    tabla = utes_filtradas.assign(
        socios=utes_filtradas.get(
            "miembros", pd.Series([[]] * len(utes_filtradas), index=utes_filtradas.index)
        ).apply(lambda ms: ", ".join(ms) if isinstance(ms, list) else ""),
    )[
        [
            "fecha_adjudicacion",
            "titulo",
            "organo_contratacion",
            "ccaa",
            "importe_adjudicado",
            "baja_pct",
            "n_ofertas_recibidas",
            "n_miembros",
            "socios",
            "url_lic",
        ]
    ].rename(columns={"url_lic": "url"})

    data_table(
        tabla.sort_values("importe_adjudicado", ascending=False).head(300),
        height=400,
        column_config={
            "fecha_adjudicacion": st.column_config.DateColumn("Adjudicación"),
            "titulo": st.column_config.TextColumn("Título", width="large"),
            "organo_contratacion": st.column_config.TextColumn("Órgano", width="medium"),
            "ccaa": st.column_config.TextColumn("CCAA", width="small"),
            "importe_adjudicado": st.column_config.NumberColumn("Importe", format="%.0f €"),
            "baja_pct": st.column_config.NumberColumn("Baja %", format="%.1f%%"),
            "n_ofertas_recibidas": st.column_config.NumberColumn("Ofertas"),
            "n_miembros": st.column_config.NumberColumn("Socios"),
            "socios": st.column_config.TextColumn("Socios (normalizados)", width="large"),
            "url": st.column_config.LinkColumn("Pliego", display_text="🔗"),
        },
    )
