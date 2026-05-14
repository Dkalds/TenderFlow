"""Página de Calidad de Datos — completitud, frescura, errores y DLQ."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from dashboard.components.kpi import kpi_card
from dashboard.components.states import empty_state, guarded_render
from dashboard.components.tables import data_table
from dashboard.pages._base import PageContext
from dashboard.stats import calidad_dato
from db.database import connect
from db.dlq import unresolved_summary


@guarded_render
def render(ctx: PageContext) -> None:
    st.subheader("Calidad de Datos")
    st.caption(
        "Completitud del dataset, frescura del scraping, tasa de errores "
        "del pipeline y estado de la cola de fallos."
    )

    # ── Datos de soporte ─────────────────────────────────────────────────
    df = ctx.df_full
    with connect() as c:
        cur = c.execute(
            "SELECT started_at, status, errores_parseo, errores_descarga, "
            "months_attempted, months_ok, months_failed "
            "FROM extraction_runs ORDER BY started_at DESC LIMIT 90"
        )
        runs = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])

    runs["started_at"] = pd.to_datetime(runs["started_at"], errors="coerce", utc=True)

    q = calidad_dato(df)
    dlq_summary = unresolved_summary()
    dlq_total = sum(row["n"] for row in dlq_summary) if dlq_summary else 0

    hoy = pd.Timestamp.now("UTC")
    freshness_h: float | None = None
    if not runs.empty and pd.notna(runs.iloc[0]["started_at"]):
        last_run_ts = runs.iloc[0]["started_at"]
        freshness_h = float((hoy - last_run_ts).total_seconds() / 3600)

    # ── KPI row 1: completitud ───────────────────────────────────────────
    st.markdown("#### Completitud del dataset")
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(
            kpi_card(
                "CPV válido",
                f"{q['pct_cpv_valido']:.1f}%",
                delta="≥8 dígitos",
                delta_up=q["pct_cpv_valido"] >= 90,
                icon="🏷",
                tooltip="% licitaciones con CPV de 8+ dígitos.",
            ),
            unsafe_allow_html=True,
        )
    with k2:
        st.markdown(
            kpi_card(
                "Importe presente",
                f"{q['pct_importe']:.1f}%",
                delta_up=q["pct_importe"] >= 80,
                icon="💶",
                tooltip="% licitaciones con importe no nulo.",
            ),
            unsafe_allow_html=True,
        )
    with k3:
        st.markdown(
            kpi_card(
                "Fecha publicación",
                f"{q['pct_fecha_pub']:.1f}%",
                delta_up=q["pct_fecha_pub"] >= 98,
                icon="📅",
                tooltip="% licitaciones con fecha de publicación válida.",
            ),
            unsafe_allow_html=True,
        )
    with k4:
        st.markdown(
            kpi_card(
                "Título válido",
                f"{q['pct_titulo']:.1f}%",
                delta=">10 chars",
                delta_up=q["pct_titulo"] >= 95,
                icon="📝",
                tooltip="% licitaciones con título no vacío de más de 10 caracteres.",
            ),
            unsafe_allow_html=True,
        )

    # ── KPI row 2: frescura + DLQ ────────────────────────────────────────
    st.markdown("#### Frescura y pipeline")
    f1, f2, f3, f4 = st.columns(4)
    with f1:
        freshness_str = f"{freshness_h:.1f}h" if freshness_h is not None else "—"
        fresh_ok = freshness_h is not None and freshness_h < 36
        st.markdown(
            kpi_card(
                "Antigüedad scrape",
                freshness_str,
                delta="objetivo <36h",
                delta_up=fresh_ok,
                icon="🕐",
                tooltip="Horas transcurridas desde el último run exitoso.",
            ),
            unsafe_allow_html=True,
        )
    with f2:
        last30 = runs[runs["started_at"] >= (hoy - pd.Timedelta(days=30))]
        ok_rate = float((last30["status"] == "ok").sum() / max(len(last30), 1) * 100)
        st.markdown(
            kpi_card(
                "Éxito pipeline 30d",
                f"{ok_rate:.0f}%",
                delta=f"{len(last30)} runs",
                delta_up=ok_rate >= 90,
                icon="✅",
            ),
            unsafe_allow_html=True,
        )
    with f3:
        total_errores_parseo = int(last30["errores_parseo"].fillna(0).sum())
        st.markdown(
            kpi_card(
                "Errores parseo 30d",
                f"{total_errores_parseo:,}",
                delta_up=total_errores_parseo == 0,
                icon="⚠️",
                tooltip="Total de errores de parseo XML acumulados en los últimos 30 días.",
            ),
            unsafe_allow_html=True,
        )
    with f4:
        st.markdown(
            kpi_card(
                "DLQ sin resolver",
                str(dlq_total),
                delta_up=dlq_total == 0,
                icon="📬",
                tooltip="Número total de fallos en la Dead Letter Queue pendientes de resolver.",
            ),
            unsafe_allow_html=True,
        )

    # ── Completitud por columna ──────────────────────────────────────────
    st.markdown("#### Completitud por columna")
    if not df.empty:
        _render_completeness_chart(df, ctx.plotly_template)
    else:
        empty_state("📊", "Sin datos", "El dataset está vacío.")

    # ── Errores de parseo por run ────────────────────────────────────────
    st.markdown("#### Errores de parseo por run (últimos 90 runs)")
    if not runs.empty:
        _render_error_trend(runs, ctx.plotly_template)
    else:
        st.info("Sin runs registrados.")

    # ── Tasa de éxito por semana ─────────────────────────────────────────
    st.markdown("#### Tasa de éxito semanal del pipeline")
    if not runs.empty:
        _render_success_rate_by_week(runs, ctx.plotly_template)

    # ── DLQ resumen ──────────────────────────────────────────────────────
    st.markdown("#### Dead Letter Queue por fuente")
    if dlq_summary:
        dlq_df = pd.DataFrame(dlq_summary)
        fig_dlq = px.bar(
            dlq_df,
            x="fuente",
            y="n",
            color="scope",
            template=ctx.plotly_template,
            labels={"fuente": "Fuente", "n": "Fallos sin resolver", "scope": "Fase"},
            height=300,
        )
        fig_dlq.update_layout(margin=dict(t=20, b=10, l=10, r=10))
        st.plotly_chart(fig_dlq, use_container_width=True)
    else:
        st.success("No hay fallos sin resolver en la DLQ. ✅")

    # ── Tabla de runs recientes con errores ──────────────────────────────
    if not runs.empty:
        with st.expander("Runs con errores de parseo"):
            errored = runs[runs["errores_parseo"].fillna(0) > 0].head(30)
            if errored.empty:
                st.success("Ningún run con errores de parseo.")
            else:
                data_table(
                    errored,
                    height=280,
                    column_config={
                        "started_at": st.column_config.DatetimeColumn("Inicio"),
                        "status": st.column_config.TextColumn("Estado"),
                        "errores_parseo": st.column_config.NumberColumn("Err. parseo"),
                        "errores_descarga": st.column_config.NumberColumn("Err. descarga"),
                    },
                )


def _render_completeness_chart(df: pd.DataFrame, template: str) -> None:
    """Gráfico de barras horizontales con % completitud por columna."""
    # Columnas de interés ordenadas por importancia
    cols_of_interest = [
        "titulo",
        "descripcion",
        "cpv",
        "importe",
        "fecha_publicacion",
        "organo_contratacion",
        "ccaa",
        "estado",
        "tipo_contrato",
        "fecha_fin_contrato",
        "url",
        "nuts_code",
    ]
    present = [c for c in cols_of_interest if c in df.columns]
    n = len(df)
    completeness = []
    for col in present:
        pct = float(df[col].notna().sum() / n * 100)
        completeness.append({"columna": col, "completitud_%": round(pct, 1)})

    comp_df = pd.DataFrame(completeness).sort_values("completitud_%")
    fig = go.Figure(
        go.Bar(
            x=comp_df["completitud_%"],
            y=comp_df["columna"],
            orientation="h",
            marker_color=[
                "#00A3E0" if v >= 90 else "#f0a500" if v >= 70 else "#e03030"
                for v in comp_df["completitud_%"]
            ],
            text=comp_df["completitud_%"].apply(lambda v: f"{v:.1f}%"),
            textposition="outside",
        )
    )
    fig.update_layout(
        template=template,
        height=max(250, len(present) * 28),
        margin=dict(t=10, b=10, l=10, r=60),
        xaxis=dict(range=[0, 105], title="% registros no nulos"),
        yaxis=dict(title=""),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_error_trend(runs: pd.DataFrame, template: str) -> None:
    """Scatter plot de errores de parseo y descarga por run."""
    plot_df = runs.sort_values("started_at").copy()
    plot_df["errores_parseo"] = plot_df["errores_parseo"].fillna(0)
    plot_df["errores_descarga"] = plot_df["errores_descarga"].fillna(0)
    plot_df["total_errores"] = plot_df["errores_parseo"] + plot_df["errores_descarga"]

    fig = px.bar(
        plot_df,
        x="started_at",
        y=["errores_parseo", "errores_descarga"],
        template=template,
        labels={"started_at": "Run", "value": "Errores", "variable": "Tipo"},
        color_discrete_map={"errores_parseo": "#f0a500", "errores_descarga": "#e03030"},
        height=280,
    )
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), barmode="stack")
    st.plotly_chart(fig, use_container_width=True)


def _render_success_rate_by_week(runs: pd.DataFrame, template: str) -> None:
    """Tasa de éxito agrupada por semana ISO."""
    weekly = (
        runs.dropna(subset=["started_at"])
        .assign(semana=lambda d: d["started_at"].dt.to_period("W").dt.start_time)
        .groupby("semana")
        .apply(
            lambda g: pd.Series(
                {
                    "total": len(g),
                    "ok": (g["status"] == "ok").sum(),
                    "tasa_pct": float((g["status"] == "ok").sum() / len(g) * 100),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    if weekly.empty:
        return
    fig = px.line(
        weekly,
        x="semana",
        y="tasa_pct",
        markers=True,
        template=template,
        labels={"semana": "Semana", "tasa_pct": "Tasa éxito (%)"},
        height=260,
    )
    fig.add_hline(y=90, line_dash="dash", line_color="green", annotation_text="Objetivo 90%")
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), yaxis=dict(range=[0, 105]))
    st.plotly_chart(fig, use_container_width=True)
