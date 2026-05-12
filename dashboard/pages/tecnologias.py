"""Página Tecnologías — distribución, evolución y cruces por tecnología detectada."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard.classifiers import tecnologia_label
from dashboard.components.cards import chart_card, top_card
from dashboard.components.kpi import kpi_card
from dashboard.components.states import guarded_render
from dashboard.components.tables import data_table
from dashboard.pages._base import PageContext
from dashboard.stats import score_oportunidad
from dashboard.utils.dates import month_start
from dashboard.utils.format import fmt_eur
from observability.logging import get_logger

log = get_logger(__name__)

# ── Helpers ─────────────────────────────────────────────────────────────


def _explode_tecnologias(df: pd.DataFrame) -> pd.DataFrame:
    """Expande filas con múltiples tecnologías (separadas por coma) en filas individuales.

    Devuelve un DataFrame con columna ``tecnologia`` ya limpia y con label legible.
    Las filas sin tecnología se etiquetan como "Sin clasificar".
    """
    out = df.copy()
    out["tecnologia"] = out["tecnologia"].fillna("SIN_CLASIFICAR")
    out["tecnologia"] = out["tecnologia"].str.split(",")
    out = out.explode("tecnologia", ignore_index=True)
    out["tecnologia"] = out["tecnologia"].str.strip()
    out["tech_label"] = out["tecnologia"].map(
        lambda t: tecnologia_label(t) if t != "SIN_CLASIFICAR" else "Sin clasificar"
    )
    return out


# ── Render principal ────────────────────────────────────────────────────


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df
    dfx = _explode_tecnologias(df)

    # Excluir "Sin clasificar" de los análisis principales (se muestra en tabla)
    dfx_classified = dfx[dfx["tecnologia"] != "SIN_CLASIFICAR"]

    # ── KPIs comparativos ───────────────────────────────────────────
    n_techs = dfx_classified["tech_label"].nunique()
    tech_counts = dfx_classified.groupby("tech_label").agg(
        n=("id_externo", "count"), importe=("importe", "sum")
    )
    if not tech_counts.empty:
        tech_lider = tech_counts["n"].idxmax()
        tech_lider_n = int(tech_counts.loc[tech_lider, "n"])  # type: ignore[arg-type]
        imp_medio = float(tech_counts["importe"].mean())
        # Tasa adjudicación media por tecnología
        adj_by_tech = (
            dfx_classified.groupby("tech_label")
            .apply(  # type: ignore[call-overload]
                lambda g: (
                    (g["estado_desc"].str.contains("Adjud", case=False, na=False).sum())
                    / max(len(g), 1)
                    * 100
                ),
                include_groups=False,
            )
            .mean()
        )
    else:
        tech_lider = "—"
        tech_lider_n = 0
        imp_medio = 0.0
        adj_by_tech = 0.0

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            kpi_card("Tecnologías detectadas", str(n_techs), icon="🔧"),
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            kpi_card(
                "Tecnología líder",
                str(tech_lider),
                delta=f"{tech_lider_n:,} licitaciones",
                icon="🏅",
            ),
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            kpi_card(
                "Importe medio / tech",
                fmt_eur(imp_medio),
                icon="💰",
            ),
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            kpi_card(
                "Tasa adjudicación",
                f"{adj_by_tech:.0f}%",
                delta="media por tecnología",
                delta_up=adj_by_tech >= 40,
                icon="✅",
            ),
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── Distribución general ────────────────────────────────────────
    cA, cB = st.columns(2)
    with cA, chart_card("Volumen (€) por tecnología"):
        if not tech_counts.empty:
            bar_n = tech_counts.reset_index().sort_values("n")
            fig = px.bar(
                bar_n,
                x="n",
                y="tech_label",
                orientation="h",
                template=ctx.plotly_template,
                color="importe",
                color_continuous_scale="Greens",
                labels={"n": "Licitaciones", "tech_label": "", "importe": "Importe €"},
            )
            fig.update_layout(height=420, margin=dict(t=20, b=10, l=10, r=10))
            fig.update_xaxes(tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True)

    with cB, chart_card("Licitaciones por tecnología"):
        if not tech_counts.empty:
            bar_e = tech_counts.reset_index().sort_values("importe")
            fig = px.bar(
                bar_e,
                x="importe",
                y="tech_label",
                orientation="h",
                template=ctx.plotly_template,
                color="n",
                color_continuous_scale="Blues",
                labels={"importe": "Importe €", "tech_label": "", "n": "Licitaciones"},
            )
            fig.update_layout(height=420, margin=dict(t=20, b=10, l=10, r=10))
            fig.update_xaxes(tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True)

    # ── Evolución temporal ──────────────────────────────────────────
    with chart_card("Evolución mensual por tecnología"):
        if (
            "fecha_publicacion" in dfx_classified.columns
            and dfx_classified["fecha_publicacion"].notna().any()
        ):
            ts = dfx_classified.dropna(subset=["fecha_publicacion"]).copy()
            ts["mes"] = month_start(ts["fecha_publicacion"])
            ts_agg = ts.groupby(["mes", "tech_label"]).agg(n=("id_externo", "count")).reset_index()

            metric_ts = st.radio(
                "Métrica",
                ["Nº licitaciones", "Importe acumulado"],
                horizontal=True,
                label_visibility="collapsed",
                key="tech_ts_metric",
            )
            if metric_ts == "Importe acumulado":
                ts_agg = (
                    ts.groupby(["mes", "tech_label"])
                    .agg(n=("importe", "sum"))
                    .reset_index()
                    .rename(columns={"n": "valor"})
                )
                y_col, y_label = "valor", "Importe €"
            else:
                ts_agg = ts_agg.rename(columns={"n": "valor"})
                y_col, y_label = "valor", "Licitaciones"

            fig = px.area(
                ts_agg,
                x="mes",
                y=y_col,
                color="tech_label",
                template=ctx.plotly_template,
                labels={"mes": "", y_col: y_label, "tech_label": "Tecnología"},
            )
            fig.update_layout(height=420, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin fechas de publicación para generar la serie temporal.")

    # ── Cruce con órganos ───────────────────────────────────────────
    with chart_card("Top órganos por tecnología", subtitle="Nº de licitaciones"):
        if not dfx_classified.empty:
            cross_org = (
                dfx_classified.groupby(["tech_label", "organo_contratacion"])
                .agg(n=("id_externo", "count"))
                .reset_index()
            )
            # Top 10 órganos globales
            top_orgs = (
                cross_org.groupby("organo_contratacion")["n"].sum().nlargest(10).index.tolist()
            )
            cross_org_top = cross_org[cross_org["organo_contratacion"].isin(top_orgs)]

            if not cross_org_top.empty:
                # Pivot para heatmap
                pivot = cross_org_top.pivot_table(
                    index="organo_contratacion",
                    columns="tech_label",
                    values="n",
                    fill_value=0,
                )
                # Truncar nombres largos
                pivot.index = pivot.index.str[:45]

                fig = px.imshow(
                    pivot,
                    template=ctx.plotly_template,
                    color_continuous_scale="Greens",
                    aspect="auto",
                    labels={"x": "Tecnología", "y": "Órgano", "color": "Licitaciones"},
                )
                fig.update_layout(height=450, margin=dict(t=20, b=10, l=10, r=10))
                st.plotly_chart(fig, use_container_width=True)

    # ── Cruce con geografía ─────────────────────────────────────────
    with chart_card("Distribución geográfica por tecnología"):
        geo_src = dfx_classified.dropna(subset=["ccaa"])
        if not geo_src.empty:
            cross_geo = (
                geo_src.groupby(["ccaa", "tech_label"]).agg(n=("id_externo", "count")).reset_index()
            )
            # Top 10 CCAA por volumen
            top_ccaa = cross_geo.groupby("ccaa")["n"].sum().nlargest(10).index.tolist()
            cross_geo_top = cross_geo[cross_geo["ccaa"].isin(top_ccaa)]

            if not cross_geo_top.empty:
                fig = px.bar(
                    cross_geo_top.sort_values("n"),
                    x="n",
                    y="ccaa",
                    color="tech_label",
                    orientation="h",
                    template=ctx.plotly_template,
                    barmode="group",
                    labels={"n": "Licitaciones", "ccaa": "", "tech_label": "Tecnología"},
                )
                fig.update_layout(height=450, margin=dict(t=20, b=10, l=10, r=10))
                fig.update_xaxes(tickformat=",.0f")
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin datos geográficos disponibles para cruzar con tecnologías.")

    # ── Tabla de detalle ────────────────────────────────────────────
    st.divider()
    st.subheader("🔎 Detalle por tecnología")

    tech_options = sorted(dfx_classified["tech_label"].unique().tolist())
    tech_sel = st.selectbox(
        "Filtrar por tecnología",
        options=[None, *tech_options],
        format_func=lambda x: "— todas las tecnologías —" if x is None else str(x),
        key="tech_detail_sel",
    )

    if tech_sel:
        sub = dfx_classified[dfx_classified["tech_label"] == tech_sel].copy()
    else:
        sub = dfx_classified.copy()

    # KPIs rápidos del subconjunto seleccionado
    n_sub = len(sub)
    imp_sub = float(sub["importe"].sum())
    imp_med_sub = float(sub["importe"].mean()) if n_sub > 0 else 0.0

    kS1, kS2, kS3 = st.columns(3)
    with kS1:
        st.markdown(
            kpi_card("Licitaciones", f"{n_sub:,}", icon="📋"),
            unsafe_allow_html=True,
        )
    with kS2:
        st.markdown(
            kpi_card("Importe total", fmt_eur(imp_sub), icon="💰"),
            unsafe_allow_html=True,
        )
    with kS3:
        st.markdown(
            kpi_card("Importe medio", fmt_eur(imp_med_sub), icon="📊"),
            unsafe_allow_html=True,
        )

    # Tabla con las licitaciones
    display_cols = [
        c
        for c in [
            "titulo",
            "organo_contratacion",
            "importe",
            "estado_desc",
            "tech_label",
            "ccaa",
            "fecha_publicacion",
        ]
        if c in sub.columns
    ]

    if not sub.empty:
        tbl = sub[display_cols].copy()
        tbl = tbl.sort_values("importe", ascending=False).head(100)
        data_table(
            tbl,
            height=500,
            column_config={
                "titulo": st.column_config.TextColumn("Título", width="large"),
                "organo_contratacion": st.column_config.TextColumn("Órgano", width="medium"),
                "importe": st.column_config.NumberColumn("Importe €", format="%.0f €"),
                "estado_desc": st.column_config.TextColumn("Estado"),
                "tech_label": st.column_config.TextColumn("Tecnología"),
                "ccaa": st.column_config.TextColumn("CCAA"),
                "fecha_publicacion": st.column_config.DateColumn(
                    "Publicación", format="DD/MM/YYYY"
                ),
            },
            key="tech_detail_table",
        )

        # Listado top 20 con top_card
        st.caption(f"Top 20 por importe — {tech_sel or 'todas las tecnologías'}")
        try:
            # Usar df original (no exploded) para scoring
            ids_sub = sub["id_externo"].unique()
            df_score = df[df["id_externo"].isin(ids_sub)].copy()
            sc = score_oportunidad(df_score)
            sub_scored = sub.merge(
                sc[["id_externo", "score", "banda"]], on="id_externo", how="left"
            )
            sub_scored["score"] = sub_scored["score"].fillna(0).astype(int)
            sub_scored = sub_scored.sort_values("score", ascending=False)
        except Exception as e:
            log.debug("tecnologias_score_oportunidad_failed", error=str(e))
            sub_scored = sub.copy()
            sub_scored["score"] = 0
            sub_scored["banda"] = "—"

        for _, row in sub_scored.head(20).iterrows():
            meta_parts = [
                str(row.get("estado_desc") or "—"),
                str(row.get("banda") or "—"),
                f"score {int(row.get('score') or 0)}/100",
            ]
            if row.get("ccaa"):
                meta_parts.append(str(row["ccaa"]))
            if row.get("organo_contratacion"):
                meta_parts.append(str(row["organo_contratacion"])[:40])
            top_card(
                amount=fmt_eur(row["importe"]),
                title=str(row["titulo"]),
                meta=" · ".join(meta_parts),
                url=row.get("url"),
                highlight=str(row.get("tech_label") or "—"),
            )
    else:
        st.info("No hay licitaciones para la tecnología seleccionada.")
