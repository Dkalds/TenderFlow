"""Página Detalle — tabla completa y vista expandida."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components.cards import status_badge
from dashboard.components.states import guarded_render
from dashboard.components.tables import data_table
from dashboard.data_loader import load_adjudicaciones
from dashboard.kpi_config import SCORING_BAND_LEVELS
from dashboard.pages._base import PageContext
from dashboard.stats import risk_flags, score_oportunidad
from dashboard.utils.export import to_excel_bytes
from dashboard.utils.format import fmt_eur, highlight_match
from observability.logging import get_logger

log = get_logger(__name__)


@guarded_render
def render(ctx: PageContext) -> None:
    df = ctx.df

    # ── Flags de riesgo + score ──────────────────────────────────────────────
    # Calculados sobre df_full para tener contexto histórico completo (CPV P10, monopolio…)
    try:
        adj_rf = load_adjudicaciones()
        rf = risk_flags(ctx.df_full, adj_rf)
        df = df.merge(
            rf[["id_externo", "riesgo_flags", "riesgo_score"]], on="id_externo", how="left"
        )
        df["riesgo_flags"] = df["riesgo_flags"].fillna("")
        df["riesgo_score"] = df["riesgo_score"].fillna(0).astype(int)
    except Exception as e:
        log.debug("detalle_risk_flags_failed", error=str(e))
        df = df.copy()
        df["riesgo_flags"] = ""
        df["riesgo_score"] = 0

    try:
        sc = score_oportunidad(ctx.df_full, adj_rf)
        df = df.merge(sc[["id_externo", "score", "banda", "desglose"]], on="id_externo", how="left")
        df["score"] = df["score"].fillna(0).astype(int)
        df["banda"] = df["banda"].fillna("—")
    except Exception as e:
        log.debug("detalle_score_oportunidad_failed", error=str(e))
        df = df.copy() if "score" not in df.columns else df
        df["score"] = 0
        df["banda"] = "—"
        df["desglose"] = pd.Series([{} for _ in range(len(df))], index=df.index, dtype=object)

    st.subheader(f"Detalle de licitaciones ({len(df)})")
    st.caption(
        "Plataforma de Contratación del Sector Público — reutilización al amparo de la Ley 37/2007"
    )

    cdl1, cdl2 = st.columns([1, 6])
    with cdl1:
        st.download_button(
            "⬇️ Excel",
            data=to_excel_bytes(df),
            file_name="licitaciones_sap.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    with cdl2:
        st.download_button(
            "⬇️ CSV",
            data=df.drop(columns=["modulos"]).to_csv(index=False).encode("utf-8-sig"),
            file_name="licitaciones_sap.csv",
            mime="text/csv",
        )

    cols = [
        "score",
        "banda",
        "fecha_publicacion",
        "titulo",
        "organo_contratacion",
        "ccaa",
        "importe",
        "moneda",
        "estado_desc",
        "tipo_proyecto",
        "modulos_str",
        "cpv_desc",
        "riesgo_flags",
        "url",
    ]
    cols = [c for c in cols if c in df.columns]
    show = df[cols].sort_values("score", ascending=False)

    data_table(
        show,
        height=600,
        column_config={
            "score": st.column_config.ProgressColumn(
                "Score", format="%d", min_value=0, max_value=100, width="small"
            ),
            "banda": st.column_config.TextColumn("Banda", width="small"),
            "fecha_publicacion": st.column_config.DatetimeColumn("Fecha", format="DD-MM-YYYY"),
            "titulo": st.column_config.TextColumn("Título", width="large"),
            "organo_contratacion": st.column_config.TextColumn("Órgano", width="medium"),
            "ccaa": st.column_config.TextColumn("CCAA", width="small"),
            "importe": st.column_config.NumberColumn("Importe", format="%.0f €"),
            "estado_desc": st.column_config.TextColumn("Estado"),
            "tipo_proyecto": st.column_config.TextColumn("Tipo"),
            "modulos_str": st.column_config.TextColumn("Módulos"),
            "cpv_desc": st.column_config.TextColumn("CPV"),
            "riesgo_flags": st.column_config.TextColumn("⚠️ Riesgo", width="medium"),
            "url": st.column_config.LinkColumn("Enlace", display_text="🔗"),
        },
    )

    st.divider()
    st.subheader("Vista expandida (top 20 por score)")
    _q = ctx.filters.q if ctx.filters.q and ctx.filters.q.strip() else ""
    for _, row in df.sort_values("score", ascending=False).head(20).iterrows():
        score_val = int(row.get("score") or 0)
        banda = str(row.get("banda") or "—")
        level = SCORING_BAND_LEVELS.get(banda, "neutral")
        badge_html = status_badge(level, banda)
        header = (
            f"{banda} · score {score_val}/100 · {fmt_eur(row['importe'])} — {row['titulo'][:80]}"
        )
        with st.expander(header):
            cE1, cE2 = st.columns([2, 1])
            with cE1:
                st.markdown(f"**Órgano:** {row.get('organo_contratacion', '—')}")
                st.markdown(
                    f"**Estado:** {row.get('estado_desc', '—')} · "
                    f"**Tipo proyecto:** {row.get('tipo_proyecto', '—')}"
                )
                st.markdown(f"**Módulos SAP detectados:** {row.get('modulos_str', '—')}")
                st.markdown(f"**CPV:** {row.get('cpv_desc', '—')}")
                st.markdown(
                    f"**Provincia / CCAA:** {row.get('provincia', '—')} · {row.get('ccaa', '—')}"
                )
                # Título con highlight de búsqueda
                titulo_hl = highlight_match(str(row.get("titulo") or ""), _q)
                st.markdown(f"**Título:** {titulo_hl}", unsafe_allow_html=True)
                st.markdown("**Descripción:**")
                desc_hl = highlight_match(str(row.get("descripcion") or "—"), _q)
                st.markdown(desc_hl, unsafe_allow_html=True)
            with cE2:
                st.markdown(badge_html, unsafe_allow_html=True)
                st.metric("Score", f"{score_val}/100")
                st.metric("Importe", fmt_eur(row["importe"]))
                desg = row.get("desglose") or {}
                if isinstance(desg, dict) and desg:
                    with st.popover("📊 Desglose score", use_container_width=True):
                        for k, v in desg.items():
                            st.markdown(f"- **{k}**: `{v:+d}`")
                flags_txt = row.get("riesgo_flags", "")
                if flags_txt:
                    st.markdown(f"**⚠️ Alertas:** {flags_txt}")
                else:
                    st.markdown("**✅ Sin alertas de riesgo**")
                if row.get("url"):
                    st.link_button(
                        "📄 Ver licitación oficial", row["url"], use_container_width=True
                    )
