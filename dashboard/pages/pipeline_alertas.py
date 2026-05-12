"""Página Pipeline & Alertas — vencimientos, oportunidades y Gantt."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state, guarded_render
from dashboard.components.tables import data_table
from dashboard.data_loader import load_adjudicaciones
from dashboard.forecast import build_forecast_df
from dashboard.pages._base import PageContext
from dashboard.stats import ratio_relicitacion, risk_flags, score_oportunidad
from dashboard.utils.dates import quarter_start
from dashboard.utils.format import fmt_eur
from observability.logging import get_logger

log = get_logger(__name__)


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    st.subheader("Pipeline & Alertas")
    st.caption(
        "Previsión de re-licitaciones, contratos próximos a vencer y "
        "ventanas de oportunidad comercial."
    )

    adj_rv = load_adjudicaciones()
    if adj_rv.empty or df.empty:
        empty_state(
            "📅",
            "Sin datos para el pipeline",
            "Se necesitan adjudicaciones con fechas de fin de contrato "
            "para construir el radar de vencimientos.",
        )
        return

    # ── Configuración ────────────────────────────────────────────────
    cRV1, cRV2, cRV3, cRV4 = st.columns(4)
    with cRV1:
        rv_horizonte = st.slider("Horizonte (meses)", 1, 36, 18, key="rv_horizonte")
    with cRV2:
        rv_ant = st.slider("Anticipación alerta (meses)", 1, 12, 6, key="rv_ant")
    with cRV3:
        rv_imp_min = st.number_input(
            "Importe mínimo (€)", min_value=0, value=0, step=50000, key="rv_imp_min"
        )
    with cRV4:
        rv_solo_mant = st.checkbox(
            "Solo Mantenimiento",
            value=False,
            key="rv_solo_mant",
            help="Desmarcar para ver todos los tipos",
        )

    fc_rv = build_forecast_df(
        df, adj_rv, meses_anticipacion=rv_ant, solo_mantenimiento=rv_solo_mant
    )

    if fc_rv.empty or fc_rv["fecha_fin_estimada"].isna().all():
        empty_state(
            "🔭",
            "Sin datos de duración estimada",
            "El modelo de previsión necesita contratos con fecha de fin o duración "
            "registrada. Prueba desactivando el filtro «Solo Mantenimiento».",
        )
        return

    hoy_rv = pd.Timestamp.now("UTC").tz_localize(None)
    horiz_fin = hoy_rv + pd.DateOffset(months=rv_horizonte)

    oport = fc_rv[
        (fc_rv["fecha_fin_estimada"] >= hoy_rv) & (fc_rv["fecha_fin_estimada"] <= horiz_fin)
    ].copy()

    if rv_imp_min > 0:
        oport = oport[oport["importe"].fillna(0) >= rv_imp_min]

    if "adjudicatarios" in oport.columns:
        oport = oport.rename(columns={"adjudicatarios": "adjudicatario_actual"})

    # ── KPIs ─────────────────────────────────────────────────────
    en_ventana = oport[oport["relicit_inicio"] <= hoy_rv]
    kv1, kv2, kv3, kv4 = st.columns(4)
    with kv1:
        st.markdown(
            kpi_card(
                "Oportunidades detectadas",
                f"{len(oport):,}",
                delta=f"próx. {rv_horizonte} meses",
                icon="🎯",
            ),
            unsafe_allow_html=True,
        )
    with kv2:
        st.markdown(
            kpi_card("Importe en juego", fmt_eur(oport["importe"].sum(skipna=True)), icon="💰"),
            unsafe_allow_html=True,
        )
    with kv3:
        st.markdown(
            kpi_card(
                "Ya en ventana de alerta",
                f"{len(en_ventana):,}",
                delta="actuar ahora",
                delta_up=False,
                icon="🔴",
            ),
            unsafe_allow_html=True,
        )
    with kv4:
        st.markdown(
            kpi_card(
                "Importe en ventana", fmt_eur(en_ventana["importe"].sum(skipna=True)), icon="🚨"
            ),
            unsafe_allow_html=True,
        )

    # ── KPIs de riesgo y tipología del pipeline ──────────────────────
    riesgo = risk_flags(oport, adj_rv) if not oport.empty else pd.DataFrame()
    if not riesgo.empty:
        oport_r = oport.merge(riesgo, on="id_externo", how="left")
        oport_r["riesgo_score"] = oport_r["riesgo_score"].fillna(0).astype(int)
        n_riesgo_alto = int((oport_r["riesgo_score"] >= 2).sum())
        imp_riesgo = float(oport_r[oport_r["riesgo_score"] >= 1]["importe"].sum(skipna=True))
        imp_total = float(oport_r["importe"].sum(skipna=True))
        pct_imp_riesgo = (imp_riesgo / imp_total * 100) if imp_total else 0.0
    else:
        n_riesgo_alto = 0
        pct_imp_riesgo = 0.0

    pct_relicit = ratio_relicitacion(oport, adj_rv)

    st.subheader("Indicadores de riesgo")
    kR1, kR2, kR3, _kR4 = st.columns(4)
    with kR1:
        st.markdown(
            kpi_card(
                "Riesgo alto",
                f"{n_riesgo_alto:,}",
                delta="≥2 flags activos",
                delta_up=False,
                icon="⚠️",
            ),
            unsafe_allow_html=True,
        )
    with kR2:
        st.markdown(
            kpi_card(
                "% Importe con riesgo",
                f"{pct_imp_riesgo:.0f}%",
                delta="al menos 1 flag",
                delta_up=pct_imp_riesgo < 30,
                icon="🛡",
            ),
            unsafe_allow_html=True,
        )
    with kR3:
        st.markdown(
            kpi_card(
                "% Re-licitaciones",
                f"{pct_relicit:.0f}%",
                delta="con ganador previo conocido",
                icon="🔄",
            ),
            unsafe_allow_html=True,
        )

    st.markdown("")

    # ── Embudo de oportunidades ──────────────────────────────────
    st.subheader("Embudo de oportunidades")
    n_total = len(oport)
    n_ventana = len(en_ventana)
    n_alto = n_riesgo_alto

    funnel_stages = ["Detectadas", "En ventana de alerta", "Riesgo alto"]
    funnel_values = [n_total, n_ventana, n_alto]

    if n_total > 0:
        fig = go.Figure(
            go.Funnel(
                y=funnel_stages,
                x=funnel_values,
                textposition="inside",
                textinfo="value+percent initial",
                marker=dict(
                    color=["#00A3E0", "#FFB627", "#E21836"],
                    line=dict(color="rgba(255,255,255,0.1)", width=1),
                ),
                connector=dict(line=dict(color="rgba(255,255,255,0.08)", width=1)),
            )
        )
        fig.update_layout(
            template=ctx.plotly_template,
            height=300,
            margin=dict(t=20, b=10, l=10, r=10),
            funnelgap=0.08,
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── Distribución horizonte + Volumen trimestral ──────────────
    cFc1, cFc2 = st.columns(2)
    with cFc1:
        st.subheader("Distribución por horizonte temporal")
        ef = (
            fc_rv.dropna(subset=["estado_forecast"])
            .groupby("estado_forecast", observed=True)
            .agg(n=("id_externo", "count"), importe=("importe", "sum"))
            .reset_index()
        )
        if not ef.empty:
            fig = px.bar(
                ef,
                x="estado_forecast",
                y="n",
                template=ctx.plotly_template,
                color="importe",
                color_continuous_scale="Greens",
                labels={"estado_forecast": "", "n": "Contratos", "importe": "Importe €"},
            )
            fig.update_layout(height=380, margin=dict(t=20, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)

    with cFc2:
        st.subheader("Volumen previsto por trimestre")
        qf = oport.dropna(subset=["fecha_fin_estimada"]).copy()
        if not qf.empty:
            qf["trimestre"] = quarter_start(qf["fecha_fin_estimada"])
            qg = (
                qf.groupby("trimestre")
                .agg(n=("id_externo", "count"), importe=("importe", "sum"))
                .reset_index()
            )
            fig = px.bar(
                qg,
                x="trimestre",
                y="importe",
                template=ctx.plotly_template,
                color_discrete_sequence=["#86BC25"],
                labels={"trimestre": "", "importe": "Importe que vence (€)"},
                hover_data=["n"],
            )
            fig.update_layout(height=380, margin=dict(t=20, b=10, l=10, r=10))
            fig.update_yaxes(tickformat=",.0f")
            st.plotly_chart(fig, use_container_width=True)

    # ── Matriz urgencia × valor ──────────────────────────────────
    st.subheader("Matriz urgencia × valor del contrato")
    if not oport.empty:
        oport["dias_restantes"] = (oport["fecha_fin_estimada"] - hoy_rv).dt.days
        oport_s = oport.dropna(subset=["importe", "dias_restantes"])
        if not oport_s.empty:
            oport_s = oport_s.copy()
            oport_s["label"] = oport_s["titulo"].str[:50]
            oport_s["prorroga"] = (
                oport_s["prorroga_descripcion"].notna()
                if "prorroga_descripcion" in oport_s.columns
                else False
            )
            fig = px.scatter(
                oport_s,
                x="dias_restantes",
                y="importe",
                color="estado_forecast",
                size="importe",
                hover_name="label",
                hover_data={
                    "organo_contratacion": True,
                    "dias_restantes": True,
                    "importe": ":,.0f",
                },
                template=ctx.plotly_template,
                color_discrete_sequence=ctx.color_sequence,
                log_y=True,
                labels={
                    "dias_restantes": "Días hasta vencimiento",
                    "importe": "Importe licitación (€, log)",
                    "estado_forecast": "Estado",
                },
            )
            fig.add_vline(
                x=rv_ant * 30,
                line_dash="dash",
                line_color="#E21836",
                annotation_text=f"Ventana alerta ({rv_ant}m)",
                annotation_position="top right",
            )
            fig.update_layout(height=480, margin=dict(t=20, b=10, l=10, r=10))
            fig.update_traces(
                hovertemplate="<b>%{hovertext}</b><br>Días: %{x}<br>Importe: %{y:,.0f} €<extra></extra>"
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "Cuadrante **izquierda-arriba**: contratos grandes "
                "con vencimiento inminente — máxima prioridad."
            )

    # ── Timeline Gantt ───────────────────────────────────────────
    st.subheader("Timeline de contratos (top 30 por valor)")
    tl_rv = oport.dropna(subset=["inicio_efectivo", "fecha_fin_estimada"]).copy()
    if not tl_rv.empty:
        tl_rv = tl_rv.nlargest(30, "importe")
        tl_rv["label"] = tl_rv["titulo"].str[:55]
        adj_col = "adjudicatario_actual" if "adjudicatario_actual" in tl_rv.columns else None
        hover_extra = {"adjudicatario_actual": True} if adj_col else {}
        fig = px.timeline(
            tl_rv,
            x_start="inicio_efectivo",
            x_end="fecha_fin_estimada",
            y="label",
            color="importe",
            color_continuous_scale="YlGn",
            template=ctx.plotly_template,
            hover_data={"organo_contratacion": True, "importe": ":,.0f", **hover_extra},
        )
        fig.add_shape(
            type="line",
            x0=hoy_rv.isoformat(),
            x1=hoy_rv.isoformat(),
            y0=0,
            y1=1,
            yref="paper",
            line=dict(color="#E21836", dash="dash", width=2),
        )
        fig.add_annotation(
            x=hoy_rv.isoformat(),
            y=1,
            yref="paper",
            text="Hoy",
            showarrow=False,
            font=dict(color="#E21836"),
            yanchor="bottom",
        )
        fig.update_yaxes(autorange="reversed")
        fig.update_layout(height=620, margin=dict(t=20, b=10, l=10, r=10), yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

    # ── Tabla de oportunidades ───────────────────────────────────
    st.subheader("Listado de oportunidades")

    # Añadir flags de riesgo + score (silencioso si falla)
    oport_display = oport.copy()
    try:
        rf = risk_flags(ctx.df_full, adj_rv)
        oport_display = oport_display.merge(
            rf[["id_externo", "riesgo_flags", "riesgo_score"]],
            on="id_externo",
            how="left",
        )
        oport_display["riesgo_flags"] = oport_display["riesgo_flags"].fillna("")
    except Exception as e:
        log.debug("pipeline_risk_flags_failed", error=str(e))
        oport_display["riesgo_flags"] = ""

    try:
        sc = score_oportunidad(ctx.df_full, adj_rv)
        oport_display = oport_display.merge(
            sc[["id_externo", "score", "banda"]], on="id_externo", how="left"
        )
        oport_display["score"] = oport_display["score"].fillna(0).astype(int)
        oport_display["banda"] = oport_display["banda"].fillna("—")
    except Exception as e:
        log.debug("pipeline_score_oportunidad_failed", error=str(e))
        oport_display["score"] = 0
        oport_display["banda"] = "—"

    # Filtro por score mínimo
    cSc1, cSc2 = st.columns([1, 3])
    with cSc1:
        score_min = st.slider(
            "Score mínimo",
            0,
            100,
            0,
            5,
            key="pa_score_min",
            help="Filtra oportunidades por el score calculado (0-100).",
        )
    if score_min > 0:
        oport_display = oport_display[oport_display["score"] >= score_min]
    with cSc2:
        st.caption(
            f"🔥 ≥75 caliente · 🟡 ≥50 atractiva · 🟦 ≥25 tibia · ⚪ descarte. "
            f"Mostrando {len(oport_display)} oportunidades."
        )

    cols_rv = [
        "score",
        "banda",
        "fecha_fin_estimada",
        "relicit_inicio",
        "titulo",
        "organo_contratacion",
        "ccaa",
        "importe",
        "estado_forecast",
        "riesgo_flags",
    ]
    if "adjudicatario_actual" in oport_display.columns:
        cols_rv.append("adjudicatario_actual")
    if "prorroga_descripcion" in oport_display.columns:
        cols_rv.append("prorroga_descripcion")
    if "url" in oport_display.columns:
        cols_rv.append("url")
    cols_rv = [c for c in cols_rv if c in oport_display.columns]
    data_table(
        oport_display[cols_rv].sort_values("score", ascending=False),
        height=480,
        column_config={
            "score": st.column_config.ProgressColumn(
                "Score", format="%d", min_value=0, max_value=100, width="small"
            ),
            "banda": st.column_config.TextColumn("Banda", width="small"),
            "fecha_fin_estimada": st.column_config.DateColumn("Fin estimado"),
            "relicit_inicio": st.column_config.DateColumn("Inicio ventana"),
            "titulo": st.column_config.TextColumn("Título", width="large"),
            "organo_contratacion": st.column_config.TextColumn("Órgano", width="medium"),
            "ccaa": st.column_config.TextColumn("CCAA", width="small"),
            "importe": st.column_config.NumberColumn("Importe lic.", format="%.0f €"),
            "estado_forecast": st.column_config.TextColumn("Estado"),
            "riesgo_flags": st.column_config.TextColumn("⚠️ Riesgo", width="medium"),
            "adjudicatario_actual": st.column_config.TextColumn(
                "Adjudicatario actual", width="medium"
            ),
            "prorroga_descripcion": st.column_config.TextColumn("Prórroga"),
            "url": st.column_config.LinkColumn("Enlace", display_text="🔗"),
        },
    )
