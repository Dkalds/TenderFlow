"""Componente de preview rápido de una licitación vía popover."""

from __future__ import annotations

import html as _html

import pandas as pd
import streamlit as st

from dashboard.utils.format import fmt_eur
from dashboard.utils.security import safe_url


def licitacion_popover(row: pd.Series, key: str) -> None:
    """Botón ☰ que abre un popover con el resumen de la licitación.

    Args:
        row: Fila del DataFrame con los datos de la licitación.
        key: Clave única para el botón (debe ser única en la página).
    """
    with st.popover("☰ Ver", use_container_width=False):
        titulo = str(row.get("titulo") or "—")
        st.markdown(f"**{_html.escape(titulo[:120])}**", unsafe_allow_html=True)
        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            st.metric("Importe", fmt_eur(row.get("importe")))
            st.caption(f"**Estado:** {row.get('estado_desc', '—')}")
            st.caption(f"**Tipo:** {row.get('tipo_proyecto', '—')}")
        with c2:
            fecha = row.get("fecha_publicacion")
            if pd.notna(fecha):
                try:
                    fecha_str = pd.Timestamp(fecha).strftime("%d/%m/%Y")  # type: ignore[arg-type]
                except Exception:
                    fecha_str = str(fecha)[:10]
            else:
                fecha_str = "—"
            st.metric("Publicación", fecha_str)
            st.caption(f"**CCAA:** {row.get('ccaa', '—')}")
            score_val = row.get("score")
            if score_val is not None:
                st.caption(f"**Score:** {int(score_val)}/100")

        st.markdown(f"**Órgano:** {row.get('organo_contratacion', '—')}")
        st.markdown(f"**CPV:** {row.get('cpv_desc', row.get('cpv', '—'))}")

        if row.get("modulos_str"):
            st.markdown(f"**Módulos SAP:** {row['modulos_str']}")

        flags = row.get("riesgo_flags", "")
        if flags:
            st.warning(f"⚠️ {flags}")

        url = row.get("url")
        href = safe_url(url)
        if href:
            st.link_button("📄 Ver en PLACSP", href, use_container_width=True)
