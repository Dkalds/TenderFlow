"""Página Resumen — top licitaciones, distribución y mercado."""

from __future__ import annotations

import html as _html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.cards import chart_card, top_card
from dashboard.components.kpi import kpi_card
from dashboard.components.states import guarded_render
from dashboard.data_loader import load_adjudicaciones
from dashboard.kpi_config import KPI_FORMULAS, KPI_THRESHOLDS
from dashboard.pages._base import PageContext
from dashboard.session_keys import LAST_VISIT_TS
from dashboard.stats import (
    calientes_hoy,
    compare_periods,
    hhi_concentracion,
    is_anomaly,
    kpi_sparkline_series,
    lead_time_medio,
    pct_oferta_unica,
    vencen_en,
    yoy_delta,
)
from dashboard.utils.format import fmt_eur
from dashboard.utils.lazy import lazy_section
from dashboard.utils.security import safe_url
from observability.logging import get_logger

log = get_logger(__name__)


def _render_top_licitaciones(df: pd.DataFrame, adj_resumen: pd.DataFrame) -> None:
    """Renderiza el ranking principal enriquecido con adjudicaciones."""
    top = df.dropna(subset=["importe"]).nlargest(10, "importe")

    if not adj_resumen.empty:
        adj_best = adj_resumen.sort_values("importe_adjudicado", ascending=False).drop_duplicates(
            subset=["licitacion_id"], keep="first"
        )[["licitacion_id", "nombre_canonico", "baja_pct", "fecha_adjudicacion"]]
        top = top.merge(
            adj_best,
            left_on="id_externo",
            right_on="licitacion_id",
            how="left",
        )

    for _, row in top.iterrows():
        empresa = row.get("nombre_canonico") or ""
        baja = row.get("baja_pct")
        fecha_adj = row.get("fecha_adjudicacion")
        parts_adj = []
        if empresa:
            parts_adj.append(f"Empresa: {empresa}")
        if pd.notna(baja):
            parts_adj.append(f"{float(str(baja)):.1f}% baja")
        if pd.notna(fecha_adj):
            parts_adj.append(pd.Timestamp(str(fecha_adj)).strftime("%d/%m/%Y"))
        adj_line = " | ".join(parts_adj)

        meta_base = (
            f"{row.get('organo_contratacion') or '-'} | "
            f"{row.get('estado_desc') or '-'} | "
            f"{row.get('tipo_proyecto') or '-'}"
        )
        meta = f"{meta_base} | {adj_line}" if adj_line else meta_base

        top_card(
            amount=fmt_eur(row["importe"]),
            title=str(row["titulo"]),
            meta=meta,
            url=row.get("url"),
            highlight=str(row.get("modulos_str") or "-"),
        )


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df
    adj_resumen = load_adjudicaciones()

    # ── Panel "Novedades desde tu última visita" ─────────────────────
    _now = pd.Timestamp.now("UTC")
    _last_visit = st.session_state.get(LAST_VISIT_TS)
    if _last_visit is not None and not df.empty:
        _fpub = df["fecha_publicacion"]
        if getattr(_fpub.dt, "tz", None) is None:
            _last_visit_cmp = _last_visit.tz_localize(None)
        else:
            _last_visit_cmp = _last_visit
        _nuevas = df[_fpub > _last_visit_cmp]
        if not _nuevas.empty:
            with st.expander(
                f"📬 {len(_nuevas)} nueva{'s' if len(_nuevas) != 1 else ''} licitaci{'ones' if len(_nuevas) != 1 else 'ón'} desde tu última visita",
                expanded=False,
            ):
                for _, _row in (
                    _nuevas.sort_values("fecha_publicacion", ascending=False).head(10).iterrows()
                ):
                    _fstr = (
                        _row["fecha_publicacion"].strftime("%d/%m/%Y")
                        if pd.notna(_row["fecha_publicacion"])
                        else "—"
                    )
                    st.markdown(
                        f"**{_fstr}** · {fmt_eur(_row.get('importe'))} · "
                        f"{_row.get('estado_desc', '—')} — {str(_row.get('titulo', '—'))[:80]}"
                    )
                if len(_nuevas) > 10:
                    st.caption(f"... y {len(_nuevas) - 10} más. Usa los filtros para explorarlas.")
    # Actualizar timestamp de última visita
    st.session_state[LAST_VISIT_TS] = _now

    # ── Banner "Para hoy" — señales accionables ─────────────────────
    _render_banner_hoy(df, adj_resumen)

    # ── Timeline de contratos publicados (último mes) ───────────────
    _render_timeline(df, ctx)

    # ── Actividad diaria + Últimas publicaciones ────────────────────
    _render_actividad_reciente(df, ctx)

    cL, cR = st.columns([2, 1])
    with cL, chart_card("Top 10 licitaciones por importe"):
        _render_top_licitaciones(df, adj_resumen)
    with cR:
        est = (
            df.groupby("estado_desc").size().reset_index(name="n").sort_values("n", ascending=False)
        )
        # fig_pie_estado se guarda para reusar en el export PDF sin reconstruir
        fig_pie_estado = None
        with chart_card("Distribución por estado"):
            if not est.empty:
                fig_pie_estado = px.pie(
                    est,
                    names="estado_desc",
                    values="n",
                    hole=0.55,
                    template=ctx.plotly_template,
                    color_discrete_sequence=ctx.color_sequence,
                )
                fig_pie_estado.update_traces(
                    textposition="outside",
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>%{value} licitaciones<br>%{percent}<extra></extra>",
                )
                fig_pie_estado.update_layout(
                    showlegend=False, height=320, margin=dict(t=10, b=10, l=10, r=10)
                )
                st.plotly_chart(fig_pie_estado, use_container_width=True)

        tp = (
            df.groupby("tipo_proyecto")
            .size()
            .reset_index(name="n")
            .sort_values("n", ascending=True)
        )
        with chart_card("Tipos de proyecto"):
            if not tp.empty:
                fig = px.bar(
                    tp,
                    x="n",
                    y="tipo_proyecto",
                    orientation="h",
                    template=ctx.plotly_template,
                    color="n",
                    color_continuous_scale="Greens",
                    labels={"n": "", "tipo_proyecto": ""},
                )
                fig.update_layout(
                    height=300,
                    showlegend=False,
                    coloraxis_showscale=False,
                    margin=dict(t=10, b=10, l=10, r=10),
                )
                st.plotly_chart(fig, use_container_width=True)

    # ── Sankey: Tipo de proyecto → Estado (lazy) ───────────────────
    with lazy_section("sankey_flujo", "Ver flujo licitaciones: Tipo → Estado") as _should_render:
        if _should_render:
            with chart_card(
                "Flujo licitaciones: Tipo → Estado",
                subtitle="Volumen por combinación tipo-estado",
            ):
                flow = (
                    df.groupby(["tipo_proyecto", "estado_desc"])
                    .agg(
                        n=("id_externo", "count"),
                        importe=("importe", "sum"),
                    )
                    .reset_index()
                )
                if not flow.empty:
                    from dashboard.theme.tokens import TOKENS

                    tipos = flow["tipo_proyecto"].unique().tolist()
                    estados = flow["estado_desc"].unique().tolist()
                    all_labels = tipos + estados

                    source_idx = [tipos.index(t) for t in flow["tipo_proyecto"]]
                    target_idx = [len(tipos) + estados.index(e) for e in flow["estado_desc"]]

                    node_colors = [TOKENS.colors.accent_primary] * len(tipos) + [
                        TOKENS.colors.success
                    ] * len(estados)
                    link_colors = ["rgba(134,188,36,0.15)"] * len(flow)

                    fig = go.Figure(
                        go.Sankey(
                            arrangement="snap",
                            node=dict(
                                pad=20,
                                thickness=20,
                                label=all_labels,
                                color=node_colors,
                                line=dict(color="rgba(255,255,255,0.1)", width=0.5),
                            ),
                            link=dict(
                                source=source_idx,
                                target=target_idx,
                                value=flow["n"].tolist(),
                                color=link_colors,
                                customdata=flow["importe"].apply(lambda v: f"{v:,.0f} €").tolist(),
                                hovertemplate="<b>%{source.label} → %{target.label}</b><br>"
                                "%{value} licitaciones<br>"
                                "Importe: %{customdata}<extra></extra>",
                            ),
                        )
                    )
                    fig.update_layout(
                        template=ctx.plotly_template,
                        height=420,
                        margin=dict(t=20, b=10, l=10, r=10),
                        font=dict(size=11, color="#A1A1AA"),
                    )
                    st.plotly_chart(fig, use_container_width=True)

    # ── Indicadores de mercado (lazy) ───────────────────────────────
    with lazy_section(
        "indicadores_mercado", "Ver indicadores de mercado y salud competitiva"
    ) as _mkt_render:
        if _mkt_render and not adj_resumen.empty:
            ids_filt = set(df["id_externo"])
            adj_r = adj_resumen[adj_resumen["licitacion_id"].isin(ids_filt)]

            cM1, cM2, cM3 = st.columns(3)
            with cM1:
                pct_pyme = (
                    (adj_r["es_pyme"] == 1).sum() / adj_r["es_pyme"].notna().sum() * 100
                    if adj_r["es_pyme"].notna().any()
                    else 0
                )
                th_pyme = KPI_THRESHOLDS["pct_pyme"]
                st.markdown(
                    kpi_card(
                        "% adjudicaciones PYMEs",
                        f"{pct_pyme:.0f}%",
                        delta="del nº de adjudicaciones",
                        delta_up=pct_pyme >= th_pyme["ok"],
                        icon="🏭",
                        tooltip=KPI_FORMULAS["pct_pyme"],
                    ),
                    unsafe_allow_html=True,
                )
            with cM2:
                top_cum = (
                    adj_r.groupby("nombre_canonico")["importe_adjudicado"]
                    .sum()
                    .sort_values(ascending=False)
                )
                top10 = (top_cum.head(10).sum() / top_cum.sum() * 100) if top_cum.sum() else 0
                th_c10 = KPI_THRESHOLDS["concentracion_top10"]
                st.markdown(
                    kpi_card(
                        "Concentración top 10",
                        f"{top10:.0f}%",
                        delta="del importe adjudicado",
                        delta_up=top10 < th_c10["ok"],
                        icon="📊",
                        tooltip=KPI_FORMULAS["concentracion_top10"],
                    ),
                    unsafe_allow_html=True,
                )
            with cM3:
                ofertas_med = adj_r["n_ofertas_recibidas"].median()
                of_txt = f"{ofertas_med:.0f}" if pd.notna(ofertas_med) else "—"
                st.markdown(
                    kpi_card(
                        "Ofertas/adjudicación",
                        of_txt,
                        delta="mediana",
                        icon="📨",
                        tooltip=KPI_FORMULAS["ofertas_adj"],
                    ),
                    unsafe_allow_html=True,
                )

            # ── Salud competitiva del mercado ─────────────────────────
            st.subheader("Salud competitiva")
            cS1, cS2, cS3 = st.columns(3)

            # Lead time — adj_r ya contiene fecha_publicacion (JOIN en load_adjudicaciones).
            lt = lead_time_medio(adj_r)
            lt_txt = f"{lt:.0f} días" if lt is not None else "—"
            with cS1:
                st.markdown(
                    kpi_card(
                        "Lead time pub→adj",
                        lt_txt,
                        delta="mediana",
                        icon="⏱",
                        tooltip=KPI_FORMULAS["lead_time"],
                    ),
                    unsafe_allow_html=True,
                )

            # HHI de concentración
            hhi_val = hhi_concentracion(adj_r)
            th_hhi = KPI_THRESHOLDS["hhi"]
            if hhi_val < th_hhi["competitivo"]:
                hhi_label = "competitivo"
                hhi_up = True
            elif hhi_val < th_hhi["moderado"]:
                hhi_label = "moderado"
                hhi_up = True
            else:
                hhi_label = "concentrado"
                hhi_up = False
            with cS2:
                st.markdown(
                    kpi_card(
                        "HHI concentración",
                        f"{hhi_val:,.0f}",
                        delta=f"mercado {hhi_label}",
                        delta_up=hhi_up,
                        icon="📊",
                        tooltip=KPI_FORMULAS["hhi"],
                    ),
                    unsafe_allow_html=True,
                )

            # % oferta única
            ou = pct_oferta_unica(adj_r)
            th_ou = KPI_THRESHOLDS["oferta_unica"]
            with cS3:
                st.markdown(
                    kpi_card(
                        "% Oferta única",
                        f"{ou:.0f}%",
                        delta="1 sola oferta recibida",
                        delta_up=ou < th_ou["ok"],
                        icon="🔒",
                        tooltip=KPI_FORMULAS["oferta_unica"],
                    ),
                    unsafe_allow_html=True,
                )

    # ── Panel comparativa de periodos ──────────────────────────────
    if ctx.filters.comparar and ctx.filters.rango and ctx.filters.rango_b:
        st.divider()
        st.subheader("📊 Comparativa de periodos")

        ra = ctx.filters.rango
        rb = ctx.filters.rango_b
        label_a = f"{ra[0]} → {ra[1]}"
        label_b = f"{rb[0]} → {rb[1]}"

        comp = compare_periods(
            ctx.df_full,
            (pd.Timestamp(ra[0], tz="UTC"), pd.Timestamp(ra[1], tz="UTC")),
            (pd.Timestamp(rb[0], tz="UTC"), pd.Timestamp(rb[1], tz="UTC")),
        )

        _labels = {
            "total": "Licitaciones",
            "importe_total": "Importe total",
            "importe_medio": "Importe medio",
            "organos": "Órganos únicos",
        }
        cols = st.columns(len(comp))
        for col, (key, vals) in zip(cols, comp.items(), strict=False):
            with col:
                va_str = fmt_eur(vals["a"]) if "importe" in key else f"{int(vals['a']):,}"
                vb_str = fmt_eur(vals["b"]) if "importe" in key else f"{int(vals['b']):,}"
                delta = vals["delta_pct"]
                arrow = "🔺" if delta > 0 else "🔻" if delta < 0 else "▬"
                st.metric(
                    label=_labels.get(key, key),
                    value=f"A: {va_str}",
                    delta=f"B: {vb_str} ({delta:+.1f}%)",
                    delta_color="normal",
                    help=f"A = {label_a} | B = {label_b} {arrow}",
                )


def _render_timeline(df: pd.DataFrame, ctx: PageContext) -> None:
    """Timeline interactivo de licitaciones publicadas en el último mes."""
    if df.empty:
        return

    ahora = pd.Timestamp.now("UTC")
    hace_30d = ahora - pd.Timedelta(days=30)
    recientes = df[df["fecha_publicacion"] >= hace_30d].copy()

    if recientes.empty:
        st.info("No hay licitaciones publicadas en los últimos 30 días.")
        return

    with chart_card(
        "Timeline de publicaciones — último mes",
        subtitle="Haz clic en un punto para ver el detalle de la licitación",
    ):
        recientes["importe_display"] = recientes["importe"].fillna(0)
        recientes["titulo_short"] = recientes["titulo"].str[:80]
        recientes["fecha_str"] = recientes["fecha_publicacion"].dt.strftime("%d/%m/%Y %H:%M")
        recientes["importe_fmt"] = recientes["importe"].apply(fmt_eur)

        # Color por estado
        fig = px.scatter(
            recientes.sort_values("fecha_publicacion"),
            x="fecha_publicacion",
            y="importe_display",
            color="estado_desc",
            size="importe_display",
            size_max=25,
            hover_name="titulo_short",
            hover_data={
                "fecha_str": True,
                "importe_fmt": True,
                "organo_contratacion": True,
                "estado_desc": True,
                "tipo_proyecto": True,
                "fecha_publicacion": False,
                "importe_display": False,
                "titulo_short": False,
            },
            labels={
                "fecha_publicacion": "Fecha publicación",
                "importe_display": "Importe (€)",
                "estado_desc": "Estado",
                "fecha_str": "Fecha",
                "importe_fmt": "Importe",
                "organo_contratacion": "Órgano",
                "tipo_proyecto": "Tipo",
            },
            template=ctx.plotly_template,
            color_discrete_sequence=ctx.color_sequence,
        )
        fig.update_layout(
            height=380,
            margin=dict(t=10, b=40, l=60, r=10),
            xaxis_title="",
            yaxis_title="Importe (€)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig.update_yaxes(tickformat=",.0f")
        st.plotly_chart(fig, use_container_width=True, key="timeline_chart")

        # ── Selector de licitación para ver detalle ──
        recientes_sorted = recientes.sort_values("fecha_publicacion", ascending=False)
        options = recientes_sorted["id_externo"].tolist()
        labels = [
            f"{row['fecha_publicacion'].strftime('%d/%m')} · "
            f"{fmt_eur(row['importe'])} · "
            f"{str(row['titulo'])[:70]}"
            for _, row in recientes_sorted.iterrows()
        ]
        label_map = dict(zip(labels, options, strict=False))

        selected_label = st.selectbox(
            "Selecciona una licitación para ver detalle:",
            options=["", *labels],
            index=0,
            key="timeline_select",
        )
        if selected_label and selected_label in label_map:
            sel_id = label_map[selected_label]
            row = recientes[recientes["id_externo"] == sel_id].iloc[0]
            _render_licitacion_detalle(row)


def _render_licitacion_detalle(row: pd.Series) -> None:
    """Muestra el detalle expandido de una licitación seleccionada."""
    with st.expander(f"📋 {row['titulo'][:100]}", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Importe", fmt_eur(row.get("importe")))
            st.caption(f"**Estado:** {row.get('estado_desc', '—')}")
        with c2:
            fecha = row.get("fecha_publicacion")
            fecha_str = pd.Timestamp(fecha).strftime("%d/%m/%Y") if pd.notna(fecha) else "—"  # type: ignore[arg-type]
            st.metric("Fecha publicación", fecha_str)
            st.caption(f"**Tipo proyecto:** {row.get('tipo_proyecto', '—')}")
        with c3:
            st.metric("CCAA", str(row.get("ccaa", "—") or "—"))
            st.caption(f"**Tipo contrato:** {row.get('tipo_contrato_desc', '—')}")

        st.markdown(f"**Órgano:** {row.get('organo_contratacion', '—')}")
        st.markdown(f"**CPV:** {row.get('cpv_desc', '—')}")

        if row.get("modulos_str"):
            st.markdown(f"**Módulos SAP:** {row['modulos_str']}")

        desc = row.get("descripcion")
        if desc and str(desc).strip():
            st.markdown("**Descripción:**")
            st.markdown(
                f'<div style="max-height:200px;overflow-y:auto;padding:8px;'
                f'background:rgba(255,255,255,0.03);border-radius:8px;font-size:0.9em">'
                f"{_html.escape(str(desc)[:2000])}</div>",
                unsafe_allow_html=True,
            )

        url = row.get("url")
        href = safe_url(url)
        if href:
            st.link_button("🔗 Ver en PLACSP", href)


def _render_actividad_reciente(df: pd.DataFrame, ctx: PageContext) -> None:
    """Heatmap de actividad diaria + tabla de últimas publicaciones."""
    if df.empty:
        return

    ahora = pd.Timestamp.now("UTC")
    hace_30d = ahora - pd.Timedelta(days=30)
    recientes = df[df["fecha_publicacion"] >= hace_30d].copy()

    cA, cB = st.columns([1, 1])
    with (
        cA,
        chart_card(
            "Actividad diaria (30 días)",
            subtitle="Nº de licitaciones publicadas por día",
        ),
    ):
        if not recientes.empty:
            daily = (
                recientes.set_index("fecha_publicacion")
                .resample("D")
                .agg(n=("id_externo", "count"), importe=("importe", "sum"))
                .reset_index()
            )
            daily["importe_fmt"] = daily["importe"].apply(fmt_eur)

            fig = px.bar(
                daily,
                x="fecha_publicacion",
                y="n",
                color="n",
                color_continuous_scale="Greens",
                hover_data={
                    "importe_fmt": True,
                    "n": True,
                    "fecha_publicacion": False,
                },
                labels={
                    "fecha_publicacion": "",
                    "n": "Licitaciones",
                    "importe_fmt": "Importe total",
                },
                template=ctx.plotly_template,
            )
            fig.update_layout(
                height=300,
                showlegend=False,
                coloraxis_showscale=False,
                margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Sin datos en los últimos 30 días.")

    with (
        cB,
        chart_card(
            "Tecnologías en el último mes",
            subtitle="Distribución de licitaciones por tecnología",
        ),
    ):
        if not recientes.empty and "tecnologia" in recientes.columns:
            tech_data = recientes.copy()
            tech_data["tecnologia"] = tech_data["tecnologia"].fillna("Sin clasificar")
            tech_data = tech_data.assign(tecnologia=tech_data["tecnologia"].str.split(",")).explode(
                "tecnologia", ignore_index=True
            )
            tech_data["tecnologia"] = tech_data["tecnologia"].str.strip()
            tech_counts = (
                tech_data.groupby("tecnologia")
                .agg(n=("id_externo", "count"))
                .reset_index()
                .sort_values("n", ascending=True)
            )
            fig = px.bar(
                tech_counts,
                x="n",
                y="tecnologia",
                orientation="h",
                template=ctx.plotly_template,
                color="n",
                color_continuous_scale="Greens",
                labels={"n": "", "tecnologia": ""},
            )
            fig.update_layout(
                height=300,
                showlegend=False,
                coloraxis_showscale=False,
                margin=dict(t=10, b=10, l=10, r=10),
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("Sin datos de tecnología.")

    # ── Últimas publicaciones con paginación ─────────────────────────
    _PAGE_SIZE = 10
    with chart_card(
        "Últimas publicaciones",
        subtitle="Licitaciones más recientes — haz clic para expandir",
    ):
        ultimas_all = df.sort_values("fecha_publicacion", ascending=False)
        _total_ultimas = len(ultimas_all)
        _total_pages = max(1, (_total_ultimas + _PAGE_SIZE - 1) // _PAGE_SIZE)
        _page_key = "resumen_ultimas_page"
        if _page_key not in st.session_state:
            st.session_state[_page_key] = 0
        _current_page = min(st.session_state[_page_key], _total_pages - 1)
        _start = _current_page * _PAGE_SIZE
        ultimas = ultimas_all.iloc[_start : _start + _PAGE_SIZE]

        for _, row in ultimas.iterrows():
            fecha = row["fecha_publicacion"]
            fecha_str = fecha.strftime("%d/%m/%Y") if pd.notna(fecha) else "—"
            imp = fmt_eur(row.get("importe"))
            estado = row.get("estado_desc", "—")
            titulo = str(row.get("titulo", "—"))[:90]
            header = f"{fecha_str} · {imp} · {estado} — {titulo}"
            with st.expander(header):
                _render_licitacion_detalle(row)

        # Controles de paginación
        if _total_pages > 1:
            _pc1, _pc2, _pc3 = st.columns([1, 4, 1])
            with _pc1:
                if st.button("← Anterior", key="ultimas_prev", disabled=_current_page == 0):
                    st.session_state[_page_key] = _current_page - 1
                    st.rerun()
            with _pc2:
                st.caption(
                    f"Página {_current_page + 1} de {_total_pages} ({_total_ultimas} licitaciones)"
                )
            with _pc3:
                if st.button(
                    "Siguiente →",
                    key="ultimas_next",
                    disabled=_current_page >= _total_pages - 1,
                ):
                    st.session_state[_page_key] = _current_page + 1
                    st.rerun()


def _render_banner_hoy(df: pd.DataFrame, adj: pd.DataFrame) -> None:
    """Banner superior con señales accionables "para hoy"."""
    if df.empty:
        return

    # Watchlist matches (si hay sesión con la lista cargada)
    watchlist_ids: set[str] = set()
    matches_session = st.session_state.get("watchlist_matches") or []
    if matches_session:
        try:
            watchlist_ids = {
                str(m.get("id_externo")) for m in matches_session if m.get("id_externo")
            }
        except Exception as e:
            log.debug("resumen_watchlist_ids_failed", error=str(e))
            watchlist_ids = set()

    # Calculos KPI
    calientes = calientes_hoy(df, adj, watchlist_ids=watchlist_ids or None)
    vencen_48 = vencen_en(df, horas=48)
    n_wl = len(watchlist_ids)

    # Nuevas últimas 24h
    hoy = pd.Timestamp.now("UTC")
    ult24h = df[df["fecha_publicacion"] >= (hoy - pd.Timedelta(hours=24))]
    n_24h = len(ult24h)

    # Anomaly: ¿las nuevas-24h son anómalas vs histórico diario?
    serie_daily = kpi_sparkline_series(df, metric="count", freq="D", periods=30)
    anom_24h = is_anomaly(float(n_24h), serie_daily[:-1] if serie_daily else [])

    # Delta vs ayer (últimas 24h anteriores)
    ayer = df[
        (df["fecha_publicacion"] >= (hoy - pd.Timedelta(hours=48)))
        & (df["fecha_publicacion"] < (hoy - pd.Timedelta(hours=24)))
    ]
    n_ayer = len(ayer)
    delta_24h = (
        f"{((n_24h - n_ayer) / n_ayer * 100):+.0f}% vs ayer" if n_ayer else f"{n_24h} nuevas"
    )

    # YoY corto para segundo KPI
    _, _, pct_n_30 = yoy_delta(df, col="importe", agg="count", days=30)

    st.subheader("Para hoy")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            kpi_card(
                "🆕 Nuevas 24h",
                f"{n_24h:,}",
                delta=delta_24h,
                delta_up=n_24h >= n_ayer,
                icon="🕐",
                sparkline=serie_daily,
                anomaly=anom_24h,
                tooltip="Licitaciones publicadas en las últimas 24 horas vs las 24h anteriores.",
            ),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            kpi_card(
                "⏰ Vencen en 48h",
                f"{vencen_48:,}",
                delta="plazo inminente",
                delta_up=False,
                icon="⚠",
                tooltip=KPI_FORMULAS["vencen_48h"],
            ),
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            kpi_card(
                "🔥 Calientes",
                f"{len(calientes):,}",
                delta="en plazo + alto importe + bajo riesgo",
                icon="🎯",
                tooltip=KPI_FORMULAS["calientes_hoy"],
            ),
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            kpi_card(
                "🔔 Watchlist",
                f"{n_wl:,}",
                delta="matches activos",
                icon="⭐",
                tooltip="Nº de licitaciones que han disparado alguna regla de tu watchlist.",
            ),
            unsafe_allow_html=True,
        )
    st.markdown("")
    _ = pct_n_30  # reservado para futuros tooltips comparativos
