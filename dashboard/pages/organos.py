"""Página Órganos — top órganos, treemap y drill-down por órgano."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.components.cards import chart_card, top_card
from dashboard.components.kpi import kpi_card
from dashboard.components.states import guarded_render
from dashboard.components.tables import data_table
from dashboard.data_loader import load_adjudicaciones
from dashboard.pages._base import PageContext
from dashboard.stats import kpis_organo, score_oportunidad
from dashboard.utils.format import fmt_eur
from observability.logging import get_logger

log = get_logger(__name__)


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    cA, cB = st.columns(2)
    with cA, chart_card("Top órganos por nº de licitaciones"):
        top_n = (
            df.groupby("organo_contratacion")
            .agg(n=("id_externo", "count"), importe=("importe", "sum"))
            .reset_index()
            .sort_values("n", ascending=False)
            .head(15)
        )
        if not top_n.empty:
            fig = px.bar(
                top_n.sort_values("n"),
                x="n",
                y="organo_contratacion",
                orientation="h",
                template=ctx.plotly_template,
                color="importe",
                color_continuous_scale="Greens",
                labels={"n": "Licitaciones", "organo_contratacion": "", "importe": "Importe €"},
            )
            fig.update_layout(height=520, margin=dict(t=20, b=10, l=10, r=10))
            fig.update_xaxes(tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True)

    with cB, chart_card("Top órganos por importe acumulado"):
        top_e = (
            df.groupby("organo_contratacion")
            .agg(importe=("importe", "sum"), n=("id_externo", "count"))
            .reset_index()
            .sort_values("importe", ascending=False)
            .head(15)
        )
        if not top_e.empty:
            fig = px.bar(
                top_e.sort_values("importe"),
                x="importe",
                y="organo_contratacion",
                orientation="h",
                template=ctx.plotly_template,
                color="n",
                color_continuous_scale="Blues",
                labels={"importe": "Importe €", "organo_contratacion": "", "n": "Licitaciones"},
            )
            fig.update_layout(height=520, margin=dict(t=20, b=10, l=10, r=10))
            fig.update_xaxes(tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True)

    with chart_card("Treemap: órganos → tipos proyecto → importe"):
        tm = df.dropna(subset=["importe"]).copy()
        if not tm.empty:
            tm["organo_short"] = tm["organo_contratacion"].fillna("—").str[:40]
            fig = px.treemap(
                tm,
                path=["organo_short", "tipo_proyecto"],
                values="importe",
                template=ctx.plotly_template,
                color="importe",
                color_continuous_scale="Greens",
            )
            fig.update_layout(height=600, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

    # ── Explorar órgano ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("🔎 Explorar órgano")
    st.caption(
        "Busca un órgano por nombre, selecciónalo y revisa su pipeline, "
        "adjudicatarios históricos y estacionalidad."
    )

    organo_q = st.text_input(
        "Filtrar por nombre del órgano",
        placeholder="Ej: AYUNTAMIENTO MADRID, JUNTA, MUTUA…",
        key="org_search",
    )
    ranking = (
        df.groupby("organo_contratacion")
        .agg(
            n=("id_externo", "count"),
            importe=("importe", "sum"),
        )
        .reset_index()
        .sort_values("importe", ascending=False)
    )
    if organo_q:
        ranking = ranking[
            ranking["organo_contratacion"].str.contains(organo_q, case=False, na=False)
        ]

    st.caption(f"📋 {len(ranking)} órganos coinciden — mostrando top 50 por importe.")
    top50 = ranking.head(50)
    n_max = int(top50["n"].max()) or 1
    data_table(
        top50,
        height=300,
        column_config={
            "organo_contratacion": st.column_config.TextColumn("Órgano", width="large"),
            "n": st.column_config.ProgressColumn(
                "Licitaciones", min_value=0, max_value=n_max, format="%d"
            ),
            "importe": st.column_config.NumberColumn("Importe €", format="%.0f €"),
        },
    )

    # ── Selector + drill-down ─────────────────────────────────────────────
    opciones = ranking.head(200)["organo_contratacion"].dropna().tolist()
    organo_sel = st.selectbox(
        "Selecciona un órgano para ver sus contratos",
        options=[None, *opciones],
        format_func=lambda x: "— elige un órgano —" if x is None else str(x),
        key="org_drill",
    )

    if not organo_sel:
        return

    sub = df[df["organo_contratacion"] == organo_sel].copy()
    if sub.empty:
        st.info("Sin datos para este órgano en el rango filtrado.")
        return

    adj_full = load_adjudicaciones()
    sub_adj = (
        adj_full[adj_full["licitacion_id"].isin(sub["id_externo"])]
        if not adj_full.empty
        else pd.DataFrame()
    )

    # ── KPIs del órgano ───────────────────────────────────────────────────
    k = kpis_organo(sub, sub_adj, organo=None)  # sub ya está filtrado
    n_lics = int(k["n_lics"] or 0)
    imp_total = float(k["importe_total"] or 0.0)
    imp_medio = float(k["importe_medio"] or 0.0)
    pct_adj = float(k["pct_adj"] or 0.0)
    lt_raw = k["lead_time_dias"]
    top_adj = k["top_adjudicatario"]
    top_adj_imp = float(k["top_adj_importe"] or 0.0)

    lt_txt = f"{float(lt_raw):.0f} d" if isinstance(lt_raw, (int, float)) else "—"

    cK1, cK2, cK3, cK4 = st.columns(4)
    with cK1:
        st.markdown(
            kpi_card("Licitaciones", f"{n_lics:,}", icon="📋"),
            unsafe_allow_html=True,
        )
    with cK2:
        st.markdown(
            kpi_card(
                "Importe total",
                fmt_eur(imp_total),
                delta=f"medio {fmt_eur(imp_medio)}",
                icon="💰",
            ),
            unsafe_allow_html=True,
        )
    with cK3:
        st.markdown(
            kpi_card(
                "% Adjudicadas",
                f"{pct_adj:.0f}%",
                delta="del total del órgano",
                delta_up=pct_adj >= 50,
                icon="✅",
            ),
            unsafe_allow_html=True,
        )
    with cK4:
        st.markdown(
            kpi_card("Lead time mediano", lt_txt, delta="pub → adj", icon="⏱"),
            unsafe_allow_html=True,
        )

    if top_adj:
        st.caption(f"🏆 **Top adjudicatario histórico:** {top_adj} ({fmt_eur(top_adj_imp)})")

    # ── Mini-charts: top adjudicatarios + estacionalidad ──────────────────
    cC1, cC2 = st.columns(2)
    with cC1:
        st.markdown("#### Top 10 adjudicatarios")
        if not sub_adj.empty and "nombre_canonico" in sub_adj.columns:
            top_adj_df = (
                sub_adj.groupby("nombre_canonico")["importe_adjudicado"]
                .sum()
                .nlargest(10)
                .reset_index()
            )
            if not top_adj_df.empty:
                fig = px.bar(
                    top_adj_df.sort_values("importe_adjudicado"),
                    x="importe_adjudicado",
                    y="nombre_canonico",
                    orientation="h",
                    template=ctx.plotly_template,
                    color="importe_adjudicado",
                    color_continuous_scale="Greens",
                    labels={"importe_adjudicado": "Importe €", "nombre_canonico": ""},
                )
                fig.update_layout(
                    height=320,
                    showlegend=False,
                    coloraxis_showscale=False,
                    margin=dict(t=10, b=10, l=10, r=10),
                )
                fig.update_xaxes(tickformat=",.0f")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sin adjudicaciones registradas para este órgano.")
        else:
            st.info("Sin adjudicaciones registradas para este órgano.")

    with cC2:
        st.markdown("#### Estacionalidad mensual")
        if "fecha_publicacion" in sub.columns and sub["fecha_publicacion"].notna().any():
            season = (
                sub.dropna(subset=["fecha_publicacion"])
                .assign(mes=lambda x: x["fecha_publicacion"].dt.month)
                .groupby("mes")
                .size()
                .reset_index(name="n")
            )
            mes_nombres = {
                1: "Ene",
                2: "Feb",
                3: "Mar",
                4: "Abr",
                5: "May",
                6: "Jun",
                7: "Jul",
                8: "Ago",
                9: "Sep",
                10: "Oct",
                11: "Nov",
                12: "Dic",
            }
            season["mes_label"] = season["mes"].map(mes_nombres)
            # Asegurar los 12 meses presentes (huecos = 0)
            full = pd.DataFrame({"mes": range(1, 13)})
            full["mes_label"] = full["mes"].map(mes_nombres)
            full = full.merge(season[["mes", "n"]], on="mes", how="left").fillna({"n": 0})
            fig = px.bar(
                full,
                x="mes_label",
                y="n",
                template=ctx.plotly_template,
                color_discrete_sequence=["#86BC25"],
                labels={"mes_label": "", "n": "Licitaciones"},
            )
            fig.update_layout(height=320, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin fechas válidas para calcular estacionalidad.")

    # ── Listado de licitaciones del órgano (ordenado por score) ──────────
    st.subheader(f"Licitaciones de {organo_sel} ({len(sub)})")
    try:
        sc = score_oportunidad(sub, sub_adj)
        sub_sorted = sub.merge(sc[["id_externo", "score", "banda"]], on="id_externo", how="left")
        sub_sorted["score"] = sub_sorted["score"].fillna(0).astype(int)
        sub_sorted = sub_sorted.sort_values("score", ascending=False)
    except Exception as e:
        log.debug("organos_score_oportunidad_failed", error=str(e))
        sub_sorted = sub.copy()
        sub_sorted["score"] = 0
        sub_sorted["banda"] = "—"

    st.caption("Ordenado por score de oportunidad (las más calientes arriba). Top 30.")

    # Enriquecer con datos de adjudicación (empresa, baja, fecha)
    if not sub_adj.empty:
        adj_best = sub_adj.sort_values("importe_adjudicado", ascending=False).drop_duplicates(
            subset=["licitacion_id"], keep="first"
        )[["licitacion_id", "nombre_canonico", "baja_pct", "fecha_adjudicacion"]]
        sub_sorted = sub_sorted.merge(
            adj_best,
            left_on="id_externo",
            right_on="licitacion_id",
            how="left",
        )

    for row in sub_sorted.head(30).itertuples(index=False):
        meta_parts = [
            str(getattr(row, "estado_desc", None) or "—"),
            str(getattr(row, "banda", None) or "—"),
            f"score {int(getattr(row, 'score', 0) or 0)}/100",
        ]
        if getattr(row, "ccaa", None):
            meta_parts.append(str(row.ccaa))
        empresa = getattr(row, "nombre_canonico", None)
        baja = getattr(row, "baja_pct", None)
        fecha_adj = getattr(row, "fecha_adjudicacion", None)
        if empresa:
            meta_parts.append(f"🏢 {empresa}")
        if pd.notna(baja):
            meta_parts.append(f"📉 {baja:.1f}% baja")
        if pd.notna(fecha_adj):
            meta_parts.append(f"📅 {pd.Timestamp(fecha_adj).strftime('%d/%m/%Y')}")
        top_card(
            amount=fmt_eur(row.importe),
            title=str(row.titulo),
            meta=" · ".join(meta_parts),
            url=getattr(row, "url", None),
            highlight=str(getattr(row, "modulos_str", None) or "—"),
        )
