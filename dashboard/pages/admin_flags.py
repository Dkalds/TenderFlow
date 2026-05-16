"""Página Admin — Feature Flags.

Permite a los administradores del sistema activar/desactivar feature flags
con rollout gradual por porcentaje o lista de usuarios.

Acceso: sólo usuarios con rol admin (user_email en OAUTH_ADMIN_EMAILS).
"""

from __future__ import annotations

import streamlit as st

from dashboard.components.states import guarded_render
from dashboard.pages._base import PageContext
from db.feature_flags import delete_flag, list_flags, set_flag


@guarded_render
def render(ctx: PageContext) -> None:
    st.title("⚑ Feature Flags")
    st.caption("Activa o desactiva funcionalidades en tiempo real sin desplegar.")

    # ── List existing flags ───────────────────────────────────────────────
    flags = list_flags()

    st.subheader("Flags activos")
    if not flags:
        st.info("No hay flags configurados todavía.")
    else:
        for flag in flags:
            with st.expander(f"{'✅' if flag['enabled'] else '❌'}  **{flag['name']}**", expanded=False):
                col1, col2, col3 = st.columns([2, 1, 1])
                new_enabled = col1.checkbox(
                    "Activo",
                    value=bool(flag["enabled"]),
                    key=f"en_{flag['name']}",
                )
                new_pct = col2.number_input(
                    "Rollout %",
                    min_value=0,
                    max_value=100,
                    value=int(flag.get("rollout_pct") or 100),
                    key=f"pct_{flag['name']}",
                )
                if col3.button("Guardar", key=f"save_{flag['name']}"):
                    set_flag(
                        flag["name"],
                        enabled=new_enabled,
                        rollout_pct=int(new_pct),
                        user_emails=flag.get("user_emails") or "",
                        description=flag.get("description") or "",
                    )
                    st.success(f"Flag **{flag['name']}** actualizado.")
                    st.rerun()

                new_emails = st.text_input(
                    "Emails allowlist (coma-separados)",
                    value=flag.get("user_emails") or "",
                    key=f"em_{flag['name']}",
                )
                new_desc = st.text_input(
                    "Descripción",
                    value=flag.get("description") or "",
                    key=f"desc_{flag['name']}",
                )
                if st.button("Actualizar emails/desc", key=f"upd_{flag['name']}"):
                    set_flag(
                        flag["name"],
                        enabled=bool(flag["enabled"]),
                        rollout_pct=int(flag.get("rollout_pct") or 100),
                        user_emails=new_emails,
                        description=new_desc,
                    )
                    st.success("Actualizado.")
                    st.rerun()

                if st.button("🗑 Eliminar flag", key=f"del_{flag['name']}", type="secondary"):
                    delete_flag(flag["name"])
                    st.warning(f"Flag **{flag['name']}** eliminado.")
                    st.rerun()

                if flag.get("updated_at"):
                    st.caption(f"Última actualización: {flag['updated_at']}")

    st.divider()

    # ── Create new flag ───────────────────────────────────────────────────
    st.subheader("Nuevo flag")
    with st.form("new_flag_form"):
        new_name = st.text_input("Nombre del flag", placeholder="ej. nueva_comparacion")
        new_desc_f = st.text_input("Descripción", placeholder="¿Para qué sirve este flag?")
        new_enabled_f = st.checkbox("Activo al crear", value=True)
        new_pct_f = st.slider("Rollout %", 0, 100, 100)
        new_emails_f = st.text_input("Emails allowlist (opcional)", placeholder="a@x.com, b@y.com")
        submitted = st.form_submit_button("Crear flag")

    if submitted:
        if not new_name or not new_name.strip():
            st.error("El nombre del flag no puede estar vacío.")
        else:
            existing = [f["name"] for f in flags]
            if new_name.strip() in existing:
                st.error(f"Ya existe un flag con nombre **{new_name.strip()}**.")
            else:
                set_flag(
                    new_name.strip(),
                    enabled=new_enabled_f,
                    rollout_pct=new_pct_f,
                    user_emails=new_emails_f,
                    description=new_desc_f,
                )
                st.success(f"Flag **{new_name.strip()}** creado.")
                st.rerun()
