"""Página Mi Watchlist — seguimiento personalizado de CPVs / keywords.

Identificamos al usuario por un ``user_key`` derivado del password configurado
(hash local, no PII). Con OAuth, se vincula al ``user_id`` de la tabla ``users``.
"""

from __future__ import annotations

import hashlib
import os

import pandas as pd
import streamlit as st

from dashboard.auth import get_current_user
from dashboard.components.states import empty_state, guarded_render
from dashboard.components.tables import data_table
from dashboard.components.toasts import notify_error, notify_success
from dashboard.pages._base import PageContext
from dashboard.utils.format import fmt_eur
from db.watchlist import (
    WatchlistEntry,
    add_entry,
    list_entries,
    remove_entry,
)


def _user_key() -> str:
    """Deriva una clave opaca para el usuario actual.

    Usa el password del dashboard o el nombre de host; nunca el valor en claro.
    """
    from config import settings

    seed = settings.DASHBOARD_PASSWORD or os.environ.get("COMPUTERNAME", "default")
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _get_user_context() -> tuple[str, int | None]:
    """Devuelve (user_key, user_id) del usuario actual."""
    user = get_current_user()
    user_id = user.get("user_id") if user else None
    return _user_key(), user_id


@guarded_render
def render(ctx: PageContext) -> None:
    st.subheader("Mi Watchlist")
    st.caption(
        "Guarda combinaciones de CPV + keywords + importe mínimo para recibir "
        "alertas cuando aparezcan licitaciones que encajen."
    )

    user_key, user_id = _get_user_context()
    entries = list_entries(user_key, user_id=user_id)

    with st.expander("➕ Añadir entrada", expanded=not entries):
        col1, col2, col3, col4 = st.columns([1, 2, 1, 1])
        with col1:
            cpv = st.text_input("CPV prefix", value="72", max_chars=8, key="wl_cpv")
        with col2:
            kw = st.text_input("Keyword (opcional)", value="", key="wl_kw")
        with col3:
            imp = st.number_input(
                "Importe min (€)", min_value=0, value=0, step=50_000, key="wl_imp"
            )
        with col4:
            ccaas = sorted(ctx.df_full["ccaa"].dropna().unique().tolist())
            ccaa = st.selectbox("CCAA (opcional)", ["(todas)", *ccaas], key="wl_ccaa")
        email = st.text_input(
            "Email de notificación (opcional)",
            value="",
            placeholder="tucorreo@ejemplo.com",
            key="wl_email",
            help="Si lo rellenas recibirás un email cada vez que aparezca "
            "una licitación que encaje con estos criterios.",
        )
        if st.button("Guardar", type="primary"):
            if not cpv.strip():
                notify_error("El CPV es obligatorio.")
            else:
                add_entry(
                    WatchlistEntry(
                        user_key=user_key,
                        cpv_prefix=cpv.strip(),
                        keyword=kw.strip() or None,
                        min_importe=float(imp) if imp else None,
                        ccaa=None if ccaa == "(todas)" else ccaa,
                        email=email.strip() or None,
                        user_id=user_id,
                    )
                )
                notify_success("Entrada guardada.")
                st.rerun()

    if not entries:
        empty_state(
            "⭐",
            "Aún no sigues ningún CPV",
            "Añade tu primera entrada para ver licitaciones relevantes destacadas aquí.",
        )
        return

    st.markdown("#### Entradas activas")
    for e in entries:
        c1, c2, c3, c4, c5, c6, c7 = st.columns([1, 2, 1, 1, 2, 2, 1])
        c1.code(e["cpv_prefix"])
        c2.write(e.get("keyword") or "—")
        c3.write(fmt_eur(e["min_importe"]) if e.get("min_importe") else "—")
        c4.write(e.get("ccaa") or "—")
        c5.caption(e.get("email") or "sin email")
        c6.caption(e.get("created_at", ""))
        if c7.button("🗑️", key=f"wl_rm_{e['id']}"):
            remove_entry(int(e["id"]))
            notify_success("Entrada eliminada.")
            st.rerun()

    st.markdown("#### Licitaciones que encajan")
    df = ctx.df.copy()
    if df.empty:
        return

    # Vectorized matching — one boolean mask per entry, OR-combined
    # NOTE: astype(str) must come BEFORE fillna("") to avoid TypeError when the
    # column is Categorical (fillna with a value not in categories raises).
    combined_mask = pd.Series(False, index=df.index)
    cpv_col = df["cpv"].astype(str).fillna("")
    titulo_col = df["titulo"].astype(str).fillna("").str.lower()
    desc_col = (
        df["descripcion"].astype(str).fillna("").str.lower()
        if "descripcion" in df.columns
        else pd.Series("", index=df.index)
    )
    text_col = titulo_col + " " + desc_col  # type: ignore[operator]
    importe_col = pd.to_numeric(df["importe"], errors="coerce").fillna(0)
    ccaa_col = df["ccaa"].astype(str).fillna("")

    for e in entries:
        entry_mask = pd.Series(True, index=df.index)
        if e.get("cpv_prefix"):
            entry_mask &= cpv_col.str.startswith(e["cpv_prefix"])
        kw = (e.get("keyword") or "").strip().lower()
        if kw:
            entry_mask &= text_col.str.contains(kw, na=False, regex=False)
        if e.get("min_importe") is not None:
            entry_mask &= importe_col >= float(e["min_importe"])
        if e.get("ccaa"):
            entry_mask &= ccaa_col == e["ccaa"]
        combined_mask |= entry_mask

    matches = df[combined_mask]

    if matches.empty:
        empty_state(
            "🔎",
            "Sin coincidencias con los filtros actuales",
            "Prueba a relajar el CPV prefix o el importe mínimo.",
        )
        return

    st.metric(
        "Coincidencias", f"{len(matches):,}", delta=fmt_eur(matches["importe"].sum(skipna=True))
    )

    cols = [
        c
        for c in (
            "fecha_publicacion",
            "titulo",
            "organo_contratacion",
            "ccaa",
            "cpv",
            "importe",
            "estado_desc",
            "url",
        )
        if c in matches.columns
    ]
    data_table(
        matches[cols].sort_values("fecha_publicacion", ascending=False),
        height=480,
        column_config={
            "fecha_publicacion": st.column_config.DateColumn("Publicación"),
            "titulo": st.column_config.TextColumn("Título", width="large"),
            "importe": st.column_config.NumberColumn("Importe", format="%.0f €"),
            "url": st.column_config.LinkColumn("Enlace", display_text="🔗"),
        },
    )
