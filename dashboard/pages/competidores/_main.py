"""Página Competidores — lógica principal de renderizado.

La sección de UTEs está en ``_utes.py`` para mantener el módulo manejable.
"""

from __future__ import annotations

import html
import re as _re
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.cards import top_card
from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state, guarded_render
from dashboard.components.tables import data_table
from dashboard.data_loader import load_adjudicaciones
from dashboard.pages._base import PageContext
from dashboard.utils.dates import month_start
from dashboard.utils.format import fmt_eur


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    st.subheader("Análisis de competidores")
    st.caption("Posicionamiento, dominio de mercado, especialización y búsqueda por empresa.")

    adj_ci = load_adjudicaciones()
    if adj_ci.empty:
        empty_state(
            "🏆",
            "Sin datos de adjudicación",
            "El pipeline aún no ha importado adjudicaciones. "
            "Ejecuta la actualización para obtener análisis de competidores.",
        )
        return

    # Restringir al filtro activo del sidebar
    ids_ci = set(df["id_externo"])
    adj_ci = adj_ci[adj_ci["licitacion_id"].isin(ids_ci)].copy()

    if adj_ci.empty:
        empty_state(
            "🔍",
            "Sin adjudicaciones para los filtros activos",
            "Prueba ampliando el rango de fechas o quitando filtros de CCAA u órgano.",
        )
        return

    # ── Selector de empresa ──────────────────────────────────────
    top_empresas = (
        adj_ci.groupby("empresa_key", dropna=True)
        .agg(nombre=("nombre_canonico", "first"), importe=("importe_adjudicado", "sum"))
        .sort_values("importe", ascending=False)
        .head(200)
    )
    opciones_ci = top_empresas["nombre"].tolist()
    sel_empresas = st.multiselect(
        "Selecciona una o varias empresas a analizar",
        opciones_ci,
        placeholder="Empieza a escribir…",
        key="ci_empresas",
    )
    if not sel_empresas:
        sel_empresas = opciones_ci[:5]
        st.caption("Mostrando top 5 por defecto.")

    keys_ci = top_empresas[top_empresas["nombre"].isin(sel_empresas)].index.tolist()
    sub_ci = adj_ci[adj_ci["empresa_key"].isin(keys_ci)].copy()
    total_mercado = adj_ci["importe_adjudicado"].sum(skipna=True)

    # ── KPIs por empresa ────────────────────────────────────────
    metr_ci = (
        sub_ci.groupby("empresa_key", dropna=True)
        .agg(
            empresa=("nombre_canonico", "first"),
            contratos=("id", "count"),
            volumen=("importe_adjudicado", "sum"),
            ticket_medio=("importe_adjudicado", "mean"),
            organos=("organo_contratacion", "nunique"),
        )
        .reset_index(drop=True)
    )
    metr_ci["cuota_pct"] = metr_ci["volumen"] / total_mercado * 100 if total_mercado else 0

    def _dep_top(s: pd.Series) -> float:
        if s.empty:
            return 0.0
        return float(s.value_counts(normalize=True).iloc[0] * 100)

    dep_pct = (
        sub_ci.groupby("empresa_key", dropna=True)["organo_contratacion"]
        .agg(_dep_top)
        .rename("dep_cliente_pct")
    )
    metr_ci = metr_ci.merge(dep_pct, left_on="empresa_key", right_index=True, how="left")

    st.subheader("KPIs de posición y dominio")
    kci_cols = st.columns(len(metr_ci) if len(metr_ci) <= 5 else 5)
    for i, row_m in enumerate(metr_ci.itertuples(index=False)):
        col_i = kci_cols[i % len(kci_cols)]
        with col_i:
            st.markdown(
                kpi_card(
                    row_m.empresa[:22],
                    fmt_eur(row_m.volumen),
                    delta=f"{row_m.cuota_pct:.1f}% cuota · {row_m.contratos} contratos",
                    delta_up=True,
                    icon="🏢",
                ),
                unsafe_allow_html=True,
            )

    st.markdown("")

    # ── Volumen + cuota de mercado ───────────────────────────────
    cCI1, cCI2 = st.columns(2)
    with cCI1:
        st.subheader("Volumen adjudicado y cuota de mercado")
        fig = px.bar(
            metr_ci.sort_values("volumen"),
            x="volumen",
            y="empresa",
            orientation="h",
            template=ctx.plotly_template,
            color="cuota_pct",
            color_continuous_scale="Greens",
            labels={"volumen": "Importe €", "empresa": "", "cuota_pct": "Cuota %"},
            hover_data=["contratos", "cuota_pct"],
        )
        fig.update_layout(height=360, margin=dict(t=10, b=10, l=10, r=10))
        fig.update_traces(hovertemplate="<b>%{y}</b><br>Importe: %{x:,.0f} €<extra></extra>")
        fig.update_xaxes(tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True)

    with cCI2:
        st.subheader("Ticket medio vs Dependencia de cliente")
        if not metr_ci.empty and "dep_cliente_pct" in metr_ci.columns:
            fig = px.scatter(
                metr_ci,
                x="ticket_medio",
                y="dep_cliente_pct",
                size="contratos",
                color="cuota_pct",
                hover_name="empresa",
                template=ctx.plotly_template,
                color_continuous_scale="RdYlGn_r",
                labels={
                    "ticket_medio": "Ticket medio (€)",
                    "dep_cliente_pct": "Dependencia cliente (%)",
                    "cuota_pct": "Cuota %",
                    "contratos": "Nº contratos",
                },
                log_x=True,
            )
            fig.update_layout(height=360, margin=dict(t=10, b=10, l=10, r=10))
            fig.update_traces(
                hovertemplate="<b>%{hovertext}</b><br>Ticket: %{x:,.0f} €<br>Dep. cliente: %{y:.1f}%<extra></extra>"
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Arriba-izquierda = tickets pequeños + cliente cautivo. "
                "Abajo-derecha = alta diversificación."
            )

    # ── Mapa de calor geográfico ─────────────────────────────────
    st.subheader("Distribución geográfica por CCAA")
    geo_ci = (
        sub_ci.dropna(subset=["ccaa"])
        .groupby(["nombre_canonico", "ccaa"])
        .agg(importe=("importe_adjudicado", "sum"))
        .reset_index()
    )
    if not geo_ci.empty:
        fig = px.density_heatmap(
            geo_ci,
            x="ccaa",
            y="nombre_canonico",
            z="importe",
            histfunc="sum",
            template=ctx.plotly_template,
            color_continuous_scale="Greens",
            labels={"ccaa": "CCAA", "nombre_canonico": "Empresa", "importe": "Importe €"},
        )
        fig.update_layout(
            height=max(280, len(sel_empresas) * 60), margin=dict(t=10, b=10, l=10, r=10)
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Treemap de especialización CPV ───────────────────────────
    st.subheader("Especialización por CPV")
    # Si una licitación tiene varios CPV, los concatenamos explícitamente
    cpv_map = (
        df.drop_duplicates(subset=["id_externo", "cpv_desc"])
        .groupby("id_externo")["cpv_desc"]
        .agg(lambda x: " / ".join(sorted(set(x.dropna()))))
    )
    cpv_ci = sub_ci.copy()
    cpv_ci["cpv_desc"] = cpv_ci["licitacion_id"].map(cpv_map)
    cpv_ci = cpv_ci.dropna(subset=["cpv_desc", "importe_adjudicado"])
    # Si el modelo de datos evoluciona a multi-CPV real, adaptar a explode
    if not cpv_ci.empty:
        fig = px.treemap(
            cpv_ci,
            path=["nombre_canonico", "cpv_desc"],
            values="importe_adjudicado",
            template=ctx.plotly_template,
            color="importe_adjudicado",
            color_continuous_scale="Greens",
            labels={"importe_adjudicado": "Importe €"},
        )
        fig.update_layout(height=480, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)

    # ── Estacionalidad ───────────────────────────────────────────
    st.subheader("Estacionalidad de adjudicaciones")
    seas_ci = sub_ci.dropna(subset=["fecha_adjudicacion"]).copy()
    if not seas_ci.empty:
        seas_ci["mes"] = month_start(seas_ci["fecha_adjudicacion"])
        seas_g = (
            seas_ci.groupby(["mes", "nombre_canonico"])
            .agg(importe=("importe_adjudicado", "sum"), n=("id", "count"))
            .reset_index()
        )
        fig = px.line(
            seas_g,
            x="mes",
            y="importe",
            color="nombre_canonico",
            markers=True,
            template=ctx.plotly_template,
            color_discrete_sequence=ctx.color_sequence,
            labels={"mes": "", "importe": "Importe adjudicado (€)", "nombre_canonico": "Empresa"},
        )
        fig.update_layout(
            height=360, margin=dict(t=10, b=10, l=10, r=10), legend=dict(orientation="h", y=-0.2)
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Análisis de nicho (keywords frecuentes) ──────────────────
    st.subheader("Perfil de nicho — palabras clave más frecuentes")
    st.caption("Extraídas de los títulos y descripciones de sus contratos.")

    _STOPWORDS = {
        "de",
        "del",
        "la",
        "el",
        "los",
        "las",
        "para",
        "por",
        "en",
        "con",
        "y",
        "a",
        "e",
        "o",
        "un",
        "una",
        "se",
        "su",
        "al",
        "que",
        "es",
        "no",
        "lo",
        "le",
        "como",
        "sus",
        "más",
        "este",
        "esta",
        "estos",
        "servicio",
        "servicios",
        "contrato",
        "lote",
    }
    nicho_cols = st.columns(min(len(sel_empresas), 3))
    for col_idx, emp_name in enumerate(sel_empresas[:3]):
        key_emp = top_empresas[top_empresas["nombre"] == emp_name].index
        if len(key_emp) == 0:
            continue
        rows_emp = sub_ci[sub_ci["empresa_key"] == key_emp[0]]
        lic_ids = set(rows_emp["licitacion_id"])
        textos = df[df["id_externo"].isin(lic_ids)].apply(
            lambda r: f"{r.get('titulo', '')} {r.get('descripcion', '')}", axis=1
        )
        words = _re.findall(r"\b[a-záéíóúüñ]{4,}\b", " ".join(textos.dropna()).lower())
        top_words = Counter(w for w in words if w not in _STOPWORDS).most_common(12)
        with nicho_cols[col_idx]:
            st.markdown(f"**{emp_name[:30]}**")
            if top_words:
                wdf = pd.DataFrame(top_words, columns=["palabra", "frecuencia"])
                fig = px.bar(
                    wdf,
                    x="frecuencia",
                    y="palabra",
                    orientation="h",
                    template=ctx.plotly_template,
                    color="frecuencia",
                    color_continuous_scale="Greys",
                    labels={"frecuencia": "", "palabra": ""},
                )
                fig.update_layout(
                    height=320,
                    showlegend=False,
                    coloraxis_showscale=False,
                    margin=dict(t=5, b=5, l=5, r=5),
                )
                st.plotly_chart(fig, use_container_width=True)

    # ── Métricas comparativas por empresa ──────────────────────────
    st.divider()
    st.subheader("Métricas comparativas por empresa")
    st.caption("Solo empresas con al menos 2 adjudicaciones.")

    def _pct_top_organo(s: pd.Series) -> float:
        if s.empty:
            return 0.0
        counts = s.value_counts(normalize=True)
        return float(counts.iloc[0] * 100)

    adj_m = adj_ci.copy()
    adj_m["es_monopolio"] = (adj_m["n_ofertas_recibidas"] == 1).astype(int)

    metr = (
        adj_m.groupby("empresa_key", dropna=False)
        .agg(
            empresa=("nombre_canonico", "first"),
            nif=("nif_norm", "first"),
            contratos=("id", "count"),
            importe_total=("importe_adjudicado", "sum"),
            importe_medio=("importe_adjudicado", "mean"),
            baja_media=("baja_pct", "mean"),
            ofertas_medias=("n_ofertas_recibidas", "mean"),
            pct_monopolio=("es_monopolio", lambda s: s.mean() * 100),
            organos=("organo_contratacion", "nunique"),
            pct_top_organo=("organo_contratacion", _pct_top_organo),
            primera=("fecha_adjudicacion", "min"),
            ultima=("fecha_adjudicacion", "max"),
        )
        .reset_index(drop=True)
    )
    metr = metr[metr["contratos"] >= 2].copy()
    if not metr.empty:
        antig_dias = (metr["ultima"] - metr["primera"]).dt.days
        antig_años = (antig_dias / 365.25).clip(lower=0.5)
        metr["contratos_año"] = (metr["contratos"] / antig_años).round(1)
        total_imp = metr["importe_total"].sum()
        metr["cuota_pct"] = metr["importe_total"] / total_imp * 100 if total_imp else 0
        metr = metr.sort_values("importe_total", ascending=False)

        data_table(
            metr[
                [
                    "empresa",
                    "nif",
                    "contratos",
                    "contratos_año",
                    "importe_total",
                    "cuota_pct",
                    "importe_medio",
                    "baja_media",
                    "ofertas_medias",
                    "pct_monopolio",
                    "organos",
                    "pct_top_organo",
                    "ultima",
                ]
            ].head(100),
            height=380,
            column_config={
                "empresa": st.column_config.TextColumn("Empresa", width="large"),
                "nif": st.column_config.TextColumn("NIF", width="small"),
                "contratos": st.column_config.NumberColumn("Contratos"),
                "contratos_año": st.column_config.NumberColumn("Contr./año"),
                "importe_total": st.column_config.NumberColumn("Importe total", format="%.0f €"),
                "cuota_pct": st.column_config.NumberColumn("Cuota %", format="%.1f%%"),
                "importe_medio": st.column_config.NumberColumn("Imp. medio", format="%.0f €"),
                "baja_media": st.column_config.NumberColumn("Baja media", format="%.1f%%"),
                "ofertas_medias": st.column_config.NumberColumn("Ofertas enfrent.", format="%.1f"),
                "pct_monopolio": st.column_config.NumberColumn("% Monopolio", format="%.0f%%"),
                "organos": st.column_config.NumberColumn("Órganos"),
                "pct_top_organo": st.column_config.NumberColumn("% top-1 órgano", format="%.0f%%"),
                "ultima": st.column_config.DateColumn("Última adj."),
            },
        )

        # Scatter: posicionamiento competitivo
        st.subheader("Mapa de posicionamiento competitivo")
        scatter = metr.dropna(subset=["importe_medio", "baja_media"]).head(60)
        if not scatter.empty:
            fig = px.scatter(
                scatter,
                x="baja_media",
                y="importe_medio",
                size="contratos",
                color="pct_monopolio",
                hover_name="empresa",
                template=ctx.plotly_template,
                color_continuous_scale="RdYlGn_r",
                log_y=True,
                labels={
                    "baja_media": "Baja media (%) — agresividad",
                    "importe_medio": "Importe medio (€, log)",
                    "pct_monopolio": "% monopolio",
                },
            )
            fig.update_layout(height=480, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Arriba-derecha: contratos grandes + baja agresiva. "
                "Arriba-izquierda rojo: clientes cautivos."
            )

    # ── Comparador side-by-side ──────────────────────────────────
    st.divider()
    st.subheader("Comparador de empresas")
    if len(sel_empresas) < 2:
        st.info(
            "Selecciona **2 o más empresas** en el selector de arriba para activar el comparador."
        )
    else:
        # Métricas enriquecidas para las empresas seleccionadas
        comp_raw = sub_ci.copy()
        comp_raw["es_mono"] = (comp_raw["n_ofertas_recibidas"] == 1).fillna(False).astype(int)

        comp_metr = (
            comp_raw.groupby("empresa_key", dropna=True)
            .agg(
                empresa=("nombre_canonico", "first"),
                contratos=("id", "count"),
                volumen=("importe_adjudicado", "sum"),
                ticket_medio=("importe_adjudicado", "mean"),
                baja_media=("baja_pct", "mean"),
                pct_monopolio=("es_mono", lambda s: float(s.mean()) * 100),
                organos=("organo_contratacion", "nunique"),
            )
            .reset_index()
        )
        comp_metr["cuota_pct"] = comp_metr["volumen"] / total_mercado * 100 if total_mercado else 0
        dep_map = {
            k: float(
                comp_raw[comp_raw["empresa_key"] == k]["organo_contratacion"]
                .value_counts(normalize=True)
                .iloc[0]
                * 100
            )
            if not comp_raw[comp_raw["empresa_key"] == k].empty
            else 0.0
            for k in comp_metr["empresa_key"]
        }
        comp_metr["dep_cliente"] = comp_metr["empresa_key"].map(dep_map).fillna(0)
        comp_metr["diversificacion"] = 100 - comp_metr["dep_cliente"]
        comp_metr = comp_metr.drop(columns=["empresa_key"])

        # ── Tabla comparativa ────────────────────────────────────
        _TABLA_METRICAS = [
            ("Volumen total", "volumen", lambda v: fmt_eur(v)),
            ("Cuota de mercado", "cuota_pct", lambda v: f"{v:.1f}%"),
            ("Nº contratos", "contratos", lambda v: f"{int(v):,}"),
            ("Ticket medio", "ticket_medio", lambda v: fmt_eur(v)),
            ("Baja media", "baja_media", lambda v: f"{v:.1f}%" if pd.notna(v) else "—"),
            ("Dependencia top-1 cliente", "dep_cliente", lambda v: f"{v:.1f}%"),
            ("Órganos distintos", "organos", lambda v: f"{int(v)}"),
            ("% Ofertas en monopolio", "pct_monopolio", lambda v: f"{v:.1f}%"),
        ]
        tabla_rows = []
        for label, col, fmt_fn in _TABLA_METRICAS:
            row_d: dict = {"Métrica": label}
            for emp_row in comp_metr.itertuples(index=False):
                val = getattr(emp_row, col, None)
                emp_name = str(emp_row.empresa)[:22]
                row_d[emp_name] = fmt_fn(val) if pd.notna(val) else "—"
            tabla_rows.append(row_d)

        cCmp1, cCmp2 = st.columns([1, 1])
        with cCmp1:
            st.markdown("**Métricas comparativas**")
            st.dataframe(
                pd.DataFrame(tabla_rows),
                use_container_width=True,
                hide_index=True,
            )

        # ── Radar chart ──────────────────────────────────────────
        with cCmp2:
            st.markdown("**Perfil competitivo (normalizado)**")
            _RADAR_COLS = {
                "cuota_pct": "Cuota %",
                "diversificacion": "Diversificación",
                "baja_media": "Agresividad precio",
                "pct_monopolio": "% Cautivo",
                "organos": "Amplitud geogr.",
                "contratos": "Actividad",
            }
            radar_df = comp_metr[
                ["empresa"] + [c for c in _RADAR_COLS if c in comp_metr.columns]
            ].copy()
            for col in _RADAR_COLS:
                if col not in radar_df.columns:
                    radar_df[col] = 0.0
                radar_df[col] = radar_df[col].fillna(0.0)
                col_min, col_max = radar_df[col].min(), radar_df[col].max()
                if col_max > col_min:
                    radar_df[col] = (radar_df[col] - col_min) / (col_max - col_min)
                else:
                    radar_df[col] = 0.5

            categories = list(_RADAR_COLS.values())
            radar_fig = go.Figure()
            colors = ctx.color_sequence
            for idx, r_row in enumerate(radar_df.itertuples(index=False)):
                vals = [float(getattr(r_row, col, 0)) for col in _RADAR_COLS]
                radar_fig.add_trace(
                    go.Scatterpolar(
                        r=[*vals, vals[0]],
                        theta=[*categories, categories[0]],
                        fill="toself",
                        name=str(r_row.empresa)[:25],
                        opacity=0.65,
                        line=dict(color=colors[idx % len(colors)]),
                    )
                )
            radar_fig.update_layout(
                template=ctx.plotly_template,
                polar=dict(
                    radialaxis=dict(visible=True, range=[0, 1], showticklabels=False),
                ),
                showlegend=True,
                height=400,
                margin=dict(t=30, b=30, l=30, r=30),
                legend=dict(orientation="h", y=-0.15),
            )
            st.plotly_chart(radar_fig, use_container_width=True)
            st.caption(
                "Cada dimensión está normalizada entre 0 y 1 dentro del grupo seleccionado. "
                "Mayor área = mejor posición relativa en ese grupo."
            )

    # ── Buscador de empresas ─────────────────────────────────────
    st.divider()
    st.subheader("Buscador de empresas")
    empresa_q = st.text_input(
        "Filtrar por nombre o NIF",
        placeholder="Ej: TELEFONICA, INDRA, B12345678...",
        key="empresa_search",
    )
    ranking = (
        adj_ci.groupby("empresa_key", dropna=False)
        .agg(
            nombre=("nombre_canonico", "first"),
            nif=("nif_norm", "first"),
            variantes=("nombre", "nunique"),
            contratos=("id", "count"),
            importe_total=("importe_adjudicado", "sum"),
            organos=("organo_contratacion", "nunique"),
            ultima=("fecha_adjudicacion", "max"),
        )
        .reset_index()
        .sort_values("importe_total", ascending=False)
    )
    if empresa_q:
        mask = ranking["nombre"].str.contains(empresa_q, case=False, na=False) | ranking[
            "nif"
        ].fillna("").str.contains(empresa_q, case=False, na=False)
        ranking = ranking[mask]

    data_table(
        ranking.drop(columns=["empresa_key"]),
        height=350,
        column_config={
            "nombre": st.column_config.TextColumn("Empresa", width="large"),
            "nif": st.column_config.TextColumn("NIF/CIF", width="small"),
            "variantes": st.column_config.NumberColumn("Variantes nombre"),
            "contratos": st.column_config.NumberColumn("Contratos"),
            "importe_total": st.column_config.NumberColumn("Importe €", format="%.0f €"),
            "organos": st.column_config.NumberColumn("Órganos"),
            "ultima": st.column_config.DateColumn("Última adj."),
        },
    )

    # ── Drill-down por empresa ───────────────────────────────────
    st.divider()
    st.subheader("Drill-down por empresa(s)")
    opciones_df = ranking[["nombre", "empresa_key"]].head(200)
    opciones = opciones_df["nombre"].tolist()
    empresas_sel_dd = st.multiselect(
        "Selecciona una o varias empresas",
        options=opciones,
        placeholder="Empieza a escribir…",
        key="drill_down_empresas",
    )
    if empresas_sel_dd:
        keys_dd = opciones_df[opciones_df["nombre"].isin(empresas_sel_dd)]["empresa_key"].tolist()
        sub_dd = adj_ci[adj_ci["empresa_key"].isin(keys_dd)].copy()

        cE1, cE2, cE3, cE4 = st.columns(4)
        cE1.metric("Empresas", len(empresas_sel_dd))
        cE2.metric("Contratos", len(sub_dd))
        cE3.metric("Importe total", fmt_eur(sub_dd["importe_adjudicado"].sum()))
        cE4.metric("Órganos distintos", sub_dd["organo_contratacion"].nunique())

        if len(empresas_sel_dd) > 1:
            comp_dd = (
                sub_dd.groupby("empresa_key")
                .agg(
                    nombre=("nombre_canonico", "first"),
                    contratos=("id", "count"),
                    importe=("importe_adjudicado", "sum"),
                )
                .reset_index(drop=True)
                .sort_values("importe", ascending=False)
            )
            cV1, cV2 = st.columns(2)
            with cV1:
                fig = px.bar(
                    comp_dd.sort_values("importe"),
                    x="importe",
                    y="nombre",
                    orientation="h",
                    template=ctx.plotly_template,
                    color="contratos",
                    color_continuous_scale="YlGn",
                    labels={"importe": "Importe €", "nombre": "", "contratos": "Contratos"},
                )
                fig.update_layout(height=350, margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(fig, use_container_width=True)
            with cV2:
                if sub_dd["fecha_adjudicacion"].notna().any():
                    evo = (
                        sub_dd.dropna(subset=["fecha_adjudicacion"])
                        .assign(mes=lambda x: month_start(x["fecha_adjudicacion"]))
                        .groupby(["mes", "nombre_canonico"])["importe_adjudicado"]
                        .sum()
                        .reset_index()
                        .rename(columns={"nombre_canonico": "nombre"})
                    )
                    fig = px.line(
                        evo,
                        x="mes",
                        y="importe_adjudicado",
                        color="nombre",
                        markers=True,
                        template=ctx.plotly_template,
                        color_discrete_sequence=ctx.color_sequence,
                        labels={"mes": "", "importe_adjudicado": "Importe €"},
                    )
                    fig.update_layout(
                        height=350,
                        margin=dict(t=10, b=10, l=10, r=10),
                        legend=dict(orientation="h", y=-0.2),
                    )
                    st.plotly_chart(fig, use_container_width=True)

        # Listado de proyectos
        st.subheader("Proyectos adjudicados")
        for empresa in empresas_sel_dd:
            key = opciones_df[opciones_df["nombre"] == empresa]["empresa_key"].iloc[0]
            emp_proy = sub_dd[sub_dd["empresa_key"] == key]
            if len(empresas_sel_dd) > 1:
                st.markdown(
                    f"**{empresa}** "
                    f"({len(emp_proy)} contratos · "
                    f"{fmt_eur(emp_proy['importe_adjudicado'].sum())})"
                )
            for row in emp_proy.sort_values("importe_adjudicado", ascending=False).itertuples(
                index=False
            ):
                url = getattr(row, "url_lic", "#") or "#"
                baja = getattr(row, "baja_pct", None)
                baja_txt = f"{baja:.1f}% baja" if pd.notna(baja) else "—"
                n_of = getattr(row, "n_ofertas_recibidas", None)
                n_of_txt = f"{int(n_of)} ofertas" if pd.notna(n_of) else "—"
                fecha_adj = (
                    row.fecha_adjudicacion.date() if pd.notna(row.fecha_adjudicacion) else "—"
                )
                top_card(
                    amount=fmt_eur(row.importe_adjudicado),
                    title=str(row.titulo or ""),
                    meta=(
                        f"{html.escape(str(getattr(row, 'organo_contratacion', '—')))} · "
                        f"Adj: {fecha_adj} · {baja_txt} · {n_of_txt}"
                    ),
                    url=url,
                )
